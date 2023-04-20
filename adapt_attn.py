
from einops import rearrange
import torch
from diffusers import UNet2DConditionModel, ControlNetModel

class CrossFrameAttnProcessor:
    def __init__(self, unet_chunk_size=2):
        self.unet_chunk_size = unet_chunk_size

    def __call__(
            self,
            attn,
            hidden_states,
            encoder_hidden_states=None,
            attention_mask=None):
        batch_size, sequence_length, _ = hidden_states.shape
        attention_mask = attn.prepare_attention_mask(attention_mask, sequence_length, batch_size)
        query = attn.to_q(hidden_states)

        is_cross_attention = encoder_hidden_states is not None
        if encoder_hidden_states is None:
            encoder_hidden_states = hidden_states
        elif attn.cross_attention_norm:
            encoder_hidden_states = attn.norm_cross(encoder_hidden_states)
        key = attn.to_k(encoder_hidden_states)
        value = attn.to_v(encoder_hidden_states)
        # Sparse Attention
        if not is_cross_attention:
            video_length = key.size()[0] // self.unet_chunk_size
            # former_frame_index = torch.arange(video_length) - 1
            # former_frame_index[0] = 0
            former_frame_index = [0] * video_length
            key = rearrange(key, "(b f) d c -> b f d c", f=video_length)
            key = key[:, former_frame_index]
            key = rearrange(key, "b f d c -> (b f) d c")
            value = rearrange(value, "(b f) d c -> b f d c", f=video_length)
            value = value[:, former_frame_index]
            value = rearrange(value, "b f d c -> (b f) d c")

        query = attn.head_to_batch_dim(query)
        key = attn.head_to_batch_dim(key)
        value = attn.head_to_batch_dim(value)

        attention_probs = attn.get_attention_scores(query, key, attention_mask)
        hidden_states = torch.bmm(attention_probs, value)
        hidden_states = attn.batch_to_head_dim(hidden_states)

        # linear proj
        hidden_states = attn.to_out[0](hidden_states)
        # dropout
        hidden_states = attn.to_out[1](hidden_states)

        return hidden_states


controlnet_attn_proc = CrossFrameAttnProcessor(
    unet_chunk_size=2)
pix2pix_attn_proc = CrossFrameAttnProcessor(
    unet_chunk_size=3)
text2video_attn_proc = CrossFrameAttnProcessor(
    unet_chunk_size=2)

def main(model_path, controlnet_path):
    unet = UNet2DConditionModel.from_pretrained(
                    model_path, subfolder="unet")

    controlnet = ControlNetModel.from_pretrained(
                    controlnet_path)

    unet.set_attn_processor(
        processor=controlnet_attn_proc)

    controlnet.set_attn_processor(
        processor=controlnet_attn_proc)

    unet.save_pretrained(save_directory=model_path.split("/")[-1] + "/unet")
    controlnet.save_pretrained(save_directory=controlnet_path.split("/")[-1])

if __name__ == "__main__":

    import argparse

    argParser = argparse.ArgumentParser()
    argParser.add_argument("-m", "--model", help="model repository on the huggingface hub")
    argParser.add_argument("-c", "--controlnet", help="controlnet model repository on the huggingface hub")

    args = argParser.parse_args()
    model_path = args.model
    controlnet_path = args.controlnet
    main(model_path, controlnet_path)