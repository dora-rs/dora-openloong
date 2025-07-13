import os
import sys
import numpy as np
import pyarrow as pa
from dora import Node
import pyrealsense2 as rs
import atexit

DEPTH_WIDTH = 1280
DEPTH_HEIGHT = 720
COLOR_WIDTH = 1280
COLOR_HEIGHT = 720
FPS = 30

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)


def main():
    # reset camera
    print("=== camera: reset start ===")
    ctx = rs.context()
    devices = ctx.query_devices()
    for dev in devices:
        dev.hardware_reset()
    print("=== camera: reset done ===")

    print("=== camera: node start ===")
    try:
        pipeline = rs.pipeline()
        config = rs.config()

        print("=== camera: config start ===")
        # 配置深度数据流
        config.enable_stream(
            rs.stream.depth, DEPTH_WIDTH, DEPTH_HEIGHT, rs.format.z16, FPS
        )
        # 配置彩色数据流
        config.enable_stream(
            rs.stream.color, COLOR_WIDTH, COLOR_HEIGHT, rs.format.bgr8, FPS
        )
        profile = pipeline.start(config)
        print("=== camera: config done ===")

        depth_sensor = profile.get_device().first_depth_sensor()
        depth_sacle = depth_sensor.get_depth_scale()
        print(f"深度传感器深度单位: {depth_sacle}")

        print("222")

        depth_profile = profile.get_stream(rs.stream.depth).as_video_stream_profile()
        depth_intrinsics = depth_profile.get_intrinsics()

        K = np.array(
            [
                [depth_intrinsics.fx, 0, depth_intrinsics.ppx],
                [0, depth_intrinsics.fy, depth_intrinsics.ppy],
                [0, 0, 1],
            ]
        )

    except Exception as e:
        print(f"配置数据流失败: {e}")
        try:
            pipeline.stop()
        except RuntimeError:
            pass
        return

    print("=== camera: start done ===")

    # 跳过前几帧，等待自动曝光稳定 (可选, 但推荐)
    for _ in range(15):
        try:
            frames = pipeline.wait_for_frames(3000)  # 等待1秒超时
            color_frame = frames.get_color_frame()
            # print("height:", color_frame.get_height())
            # print("width:", color_frame.get_width())
        except RuntimeError as e:
            print(f"预热时获取帧失败: {e}")
            # 如果在预热阶段就无法获取帧，可能存在严重问题，选择退出
            return

    print("=== camera: preheat done ===")

    node = Node()

    for event in node:
        if event["type"] == "INPUT" and event["id"] == "tick":
            try:
                frames = pipeline.wait_for_frames(200)
            except Exception as e:
                print(f"获取帧失败: {e}")
                continue

            # 检查 frames 是否为 None
            if frames is None:
                print("未获取到有效帧，跳过本次处理")
                continue

            # 处理彩色帧
            color_frame = frames.get_color_frame()
            if color_frame is None:
                print("未获取到彩色帧")
                continue
            color_image = np.asanyarray(color_frame.get_data())
            node.send_output(
                "image_depth",
                pa.array(color_image.ravel()),
                metadata={
                    "encoding": "bgr8",
                    "width": color_frame.get_width(),
                    "height": color_frame.get_height(),
                },
            )

            # 处理深度帧
            depth_frame = frames.get_depth_frame()
            if depth_frame is None:
                print("未获取到深度帧")
                continue

            depth_image_raw = np.asanyarray(depth_frame.get_data())

            # 将深度数据转换为 float64 并应用 scale 转换为米
            depth_float_meters = depth_image_raw.astype(np.float64) * depth_sacle
            depth_float_meters = np.ascontiguousarray(
                depth_float_meters
            )  # 确保内存连续

            node.send_output(
                "depth",
                pa.array(depth_float_meters.ravel()),
                metadata={
                    "width": depth_frame.get_width(),
                    "height": depth_frame.get_height(),
                    "focal": [int(K[0, 0]), int(K[1, 1])],
                    "resolution": [int(K[0, 2]), int(K[1, 2])],
                },
            )


if __name__ == "__main__":
    main()
