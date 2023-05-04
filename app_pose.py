from model import Model
import gradio as gr
import os
on_huggingspace = os.environ.get("SPACE_AUTHOR_NAME") == "PAIR"

examples = [
    ['Motion 1', "An astronaut dancing in the outer space"],
    ['Motion 2', "An astronaut dancing in the outer space"],
    ['Motion 3', "An astronaut dancing in the outer space"],
    ['Motion 4', "An astronaut dancing in the outer space"],
    ['Motion 5', "An astronaut dancing in the outer space"],
]


def create_demo(model: Model):
    with gr.Blocks() as demo:
        with gr.Row():
            gr.Markdown('## Text and Pose Conditional Video Generation')

        with gr.Row():
            gr.Markdown(
                'Selection: **one motion** and a **prompt**, or use the examples below.')
            with gr.Column():
                gallery_pose_sequence = gr.Gallery(label="Pose Sequence", value=[('__assets__/poses_skeleton_gifs/dance1.gif', "Motion 1"), ('__assets__/poses_skeleton_gifs/dance2.gif', "Motion 2"), (
                    '__assets__/poses_skeleton_gifs/dance3.gif', "Motion 3"), ('__assets__/poses_skeleton_gifs/dance4.gif', "Motion 4"), ('__assets__/poses_skeleton_gifs/dance5.gif', "Motion 5")]).style(grid=[2], height="auto")
                input_video_path = gr.Textbox(
                    label="Pose Sequence", visible=False, value="Motion 1")
                gr.Markdown("## Selection")
                pose_sequence_selector = gr.Markdown(
                    'Pose Sequence: **Motion 1**')
            with gr.Column():
                prompt = gr.Textbox(label='Prompt')
                motion_field_strength_x = gr.Slider(label="Motion field strength horizontal", minimum = -10, maximum = 10, value = 0, step=1)
                motion_field_strength_y = gr.Slider(label="Motion field strength vertical", minimum = -10, maximum = 10, value = 0, step=1)
                smooth_bg_strength = gr.Slider(label="Strength of background smoothing", minimum = 0, maximum = 1, value=0.8, step=0.01)
                lora_scale = gr.Slider(label="Scale of lora model", minimum = 0, maximum = 1, value=0.8, step=0.01)
                prng = gr.Slider(label="PRNG seed", minimum = 0, maximum = 1000, value=0, step=1)
                added_prompt = gr.Textbox(label='Added prompt modifer', value='high quality, anatomically correct, clay stop-motion, aardman, claymation, smooth')
                run_button = gr.Button(label='Run')
                with gr.Accordion('Advanced options', open=False):
                    watermark = gr.Radio(["Picsart AI Research", "Text2Video-Zero",
                                         "None"], label="Watermark", value='Picsart AI Research')
                    chunk_size = gr.Slider(
                        label="Chunk size", minimum=2, maximum=16, value=8, step=1, visible=not on_huggingspace,
                        info="Number of frames processed at once. Reduce for lower memory usage.")
                    merging_ratio = gr.Slider(
                        label="Merging ratio", minimum=0.0, maximum=0.9, step=0.1, value=0.0, visible=not on_huggingspace,
                        info="Ratio of how many tokens are merged. The higher the more compression (less memory and faster inference).")
            with gr.Column():
                result = gr.Image(label="Generated Video")

        input_video_path.change(on_video_path_update,
                                None, pose_sequence_selector)
        gallery_pose_sequence.select(
            pose_gallery_callback, None, input_video_path)
        inputs = [
            input_video_path,
            prompt,
            added_prompt,
            chunk_size,
            lora_scale,
            prng,
            smooth_bg_strength,
            motion_field_strength_x,
            motion_field_strength_y,
            # watermark,
            # merging_ratio,
        ]

        gr.Examples(examples=examples,
                    inputs=inputs,
                    outputs=result,
                    fn=model.process_controlnet_pose,
                    cache_examples=on_huggingspace,
                    run_on_click=False,
                    )

        run_button.click(fn=model.process_controlnet_pose,
                         inputs=inputs,
                         outputs=result,)

    return demo


def on_video_path_update(evt: gr.EventData):
    return f'Selection: **{evt._data}**'


def pose_gallery_callback(evt: gr.SelectData):
    return f"Motion {evt.index+1}"