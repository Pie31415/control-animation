import torch
from enum import Enum
import gc
import numpy as np
import jax.numpy as jnp
import jax

from PIL import Image
from typing import List

from flax.training.common_utils import shard
from flax.jax_utils import replicate
from flax import jax_utils
import einops

from transformers import CLIPTokenizer, CLIPFeatureExtractor, FlaxCLIPTextModel
from diffusers import (
    FlaxDDIMScheduler,
    FlaxAutoencoderKL,
    FlaxStableDiffusionControlNetPipeline,
    StableDiffusionPipeline,
    FlaxUNet2DConditionModel,
)
from text_to_animation.models.unet_2d_condition_flax import (
    FlaxUNet2DConditionModel as CustomFlaxUNet2DConditionModel,
)
from diffusers import FlaxControlNetModel

from text_to_animation.pipelines.text_to_video_pipeline_flax import (
    FlaxTextToVideoPipeline,
)

import utils.utils as utils
import utils.gradio_utils as gradio_utils
import os

on_huggingspace = os.environ.get("SPACE_AUTHOR_NAME") == "PAIR"

unshard = lambda x: einops.rearrange(x, "d b ... -> (d b) ...")


class ModelType(Enum):
    Text2Video = 1
    ControlNetPose = 2
    StableDiffusion = 3


def replicate_devices(array):
    return jnp.expand_dims(array, 0).repeat(jax.device_count(), 0)


class ControlAnimationModel:
    def __init__(self, dtype, **kwargs):
        self.dtype = dtype
        self.rng = jax.random.PRNGKey(0)
        self.pipe = None
        self.model_type = None

        self.states = {}
        self.model_name = ""

    def set_model(
        self,
        model_id: str,
        **kwargs,
    ):
        if hasattr(self, "pipe") and self.pipe is not None:
            del self.pipe
            self.pipe = None
        gc.collect()

        controlnet, controlnet_params = FlaxControlNetModel.from_pretrained(
            "fusing/stable-diffusion-v1-5-controlnet-openpose",
            from_pt=True,
            dtype=jnp.float16,
        )

        scheduler, scheduler_state = FlaxDDIMScheduler.from_pretrained(
            model_id, subfolder="scheduler", from_pt=True
        )
        tokenizer = CLIPTokenizer.from_pretrained(model_id, subfolder="tokenizer")
        feature_extractor = CLIPFeatureExtractor.from_pretrained(
            model_id, subfolder="feature_extractor"
        )
        unet, unet_params = CustomFlaxUNet2DConditionModel.from_pretrained(
            model_id, subfolder="unet", from_pt=True, dtype=self.dtype
        )
        unet_vanilla, _ = FlaxUNet2DConditionModel.from_pretrained(
            model_id, subfolder="unet", from_pt=True, dtype=self.dtype
        )
        vae, vae_params = FlaxAutoencoderKL.from_pretrained(
            model_id, subfolder="vae", from_pt=True, dtype=self.dtype
        )
        text_encoder = FlaxCLIPTextModel.from_pretrained(
            model_id, subfolder="text_encoder", from_pt=True, dtype=self.dtype
        )
        self.pipe = FlaxTextToVideoPipeline(
            vae=vae,
            text_encoder=text_encoder,
            tokenizer=tokenizer,
            unet=unet,
            unet_vanilla=unet_vanilla,
            controlnet=controlnet,
            scheduler=scheduler,
            safety_checker=None,
            feature_extractor=feature_extractor,
        )
        self.params = {
            "unet": unet_params,
            "vae": vae_params,
            "scheduler": scheduler_state,
            "controlnet": controlnet_params,
            "text_encoder": text_encoder.params,
        }
        self.p_params = jax_utils.replicate(self.params)
        self.model_name = model_id

    def generate_initial_frames(
        self,
        prompt: str,
        video_path: str,
        n_prompt: str = "",
        num_imgs: int = 4,
        resolution: int = 512,
        model_id: str = "runwayml/stable-diffusion-v1-5",
    ) -> List[Image.Image]:
        self.set_model(model_id=model_id)

        video_path = gradio_utils.motion_to_video_path(video_path)

        added_prompt = "high quality, best quality, HD, clay stop-motion, claymation, HQ, masterpiece, art, smooth"
        prompts = added_prompt + ", " + prompt

        added_n_prompt = "longbody, lowres, bad anatomy, bad hands, missing fingers, extra digit, fewer difits, cropped, worst quality, low quality, deformed body, bloated, ugly"
        negative_prompts = added_n_prompt + ", " + n_prompt

        video, fps = utils.prepare_video(
            video_path, resolution, None, self.dtype, False, output_fps=4
        )
        control = utils.pre_process_pose(video, apply_pose_detect=False)

        seeds = [seed for seed in jax.random.randint(self.rng, [num_imgs], 0, 65536)]
        prngs = [jax.random.PRNGKey(seed) for seed in seeds]
        images = self.pipe.generate_starting_frames(
            params=self.params,
            prngs=prngs,
            controlnet_image=control,
            prompt=prompts,
            neg_prompt=negative_prompts,
        )

        images = [np.array(images[i]) for i in range(images.shape[0])]

        return images

    def generate_animation(
        self,
        prompt: str,
        initial_frame_index: int,
        input_video_path: str,
        model_link: str = "dreamlike-art/dreamlike-photoreal-2.0",
        motion_field_strength_x: int = 12,
        motion_field_strength_y: int = 12,
        t0: int = 44,
        t1: int = 47,
        n_prompt: str = "",
        chunk_size: int = 8,
        video_length: int = 8,
        merging_ratio: float = 0.0,
        seed: int = 0,
        resolution: int = 512,
        fps: int = 2,
        use_cf_attn: bool = True,
        use_motion_field: bool = True,
        smooth_bg: bool = False,
        smooth_bg_strength: float = 0.4,
        path: str = None,
    ):
        video_path = gradio_utils.motion_to_video_path(video_path)

        # added_prompt = 'best quality, HD, clay stop-motion, claymation, HQ, masterpiece, art, smooth'
        # added_prompt = 'high quality, anatomically correct, clay stop-motion, aardman, claymation, smooth'
        added_n_prompt = "longbody, lowres, bad anatomy, bad hands, missing fingers, extra digit, fewer difits, cropped, worst quality, low quality, deformed body, bloated, ugly"
        negative_prompts = added_n_prompt + ", " + n_prompt

        video, fps = utils.prepare_video(
            video_path, resolution, None, self.dtype, False, output_fps=4
        )
        control = utils.pre_process_pose(video, apply_pose_detect=False)
        f, _, h, w = video.shape

        prng_seed = jax.random.PRNGKey(seed)
        vid = self.pipe.generate_video(
            prompt,
            image=control,
            params=self.params,
            prng_seed=prng_seed,
            neg_prompt="",
            controlnet_conditioning_scale=1.0,
            motion_field_strength_x=3,
            motion_field_strength_y=4,
            jit=True,
        ).image
        return utils.create_gif(np.array(vid), 4, path=None, watermark=None)
