import os
import pyarrow as pa
from dora import Node

# 如果未设置环境变量，则使用默认值
IMAGE_RESIZE_RATIO = float(os.getenv("IMAGE_RESIZE_RATIO", "1.0"))
node = Node()

ACTIVATION_WORDS = os.getenv("ACTIVATION_WORDS", "").split()
TABLE_HEIGHT = float(os.getenv("TABLE_HEIGHT", "-0.41"))

l_init_pose = [0.0, 0.0, 0.0]
r_init_pose = [0.0, 0.0, 0.0]
stop = True  # 全局变量，用于控制是否停止执行


def handle_speech(last_text):
    global stop
    # word_list = list(last_text.lower())
    words = last_text.lower().split()
    print("words: ", words)
    if len(ACTIVATION_WORDS) > 0 and any(word in ACTIVATION_WORDS for word in words):
        node.send_output(
            "text_vlm",
            pa.array(
                [
                    f"Given the prompt: {cache['text']}. Output the two bounding boxes for the two objects",
                    # f"给定提示: {cache['text']}。输出两个物体的边界框",
                ],
            ),
            metadata={"image_id": "image_depth"},
        )
        node.send_output(
            "prompt",
            pa.array([cache["text"]]),
            metadata={"image_id": "image_depth"},
        )
        print(f"sending: {cache['text']}")
        stop = False


def wait_for_event(id, timeout=None, cache={}):
    while True:
        event = node.next(timeout=timeout)
        if event is None:
            cache["finished"] = True
            return None, cache
        if event["type"] == "INPUT":
            cache[event["id"]] = event["value"]
            if event["id"] == "text":
                cache[event["id"]] = event["value"][0].as_py()
                handle_speech(event["value"][0].as_py())
            elif event["id"] == id:
                return event["value"], cache

        elif event["type"] == "ERROR":
            return None, cache


def wait_for_events(ids: list[str], timeout=None, cache={}):
    response = {}
    while True:
        event = node.next(timeout=timeout)
        if event is None:
            cache["finished"] = True
            return None, cache
        if event["type"] == "INPUT":
            cache[event["id"]] = event["value"]
            if event["id"] == "text":
                cache[event["id"]] = event["value"][0].as_py()
                handle_speech(event["value"][0].as_py())
            elif event["id"] in ids:
                response[event["id"]] = event["value"]
                if len(response) == len(ids):
                    return response, cache
        elif event["type"] == "ERROR":
            return None, cache


def get_prompt():
    """TODO: Add docstring."""
    text = wait_for_event(id="text", timeout=0.3)
    if text is None:
        return None
    text = text[0].as_py()
    words = text.lower().split()
    print("words: ", words)
    # Check if any activation word is present in the text
    if len(ACTIVATION_WORDS) > 0 and all(
        word not in ACTIVATION_WORDS for word in words
    ):
        return None
    return text


last_text = ""
cache = {"text": "Put the orange in the metal box"}

# 用于第一次运行初始化，只会运行一次
node.send_output(
    "action_r_arm",
    pa.array(r_init_pose, type=pa.float64()),
    metadata={"encoding": "jointstate", "arm": "right"},
)
print("---")
print("send r arm init pose")
node.send_output(
    "action_l_arm",
    pa.array(l_init_pose, type=pa.float64()),
    metadata={"encoding": "jointstate", "arm": "left"},
)
print("---")
print("send l arm init pose")
_, cache = wait_for_events(
    ids=["response_r_arm", "response_l_arm"],
    timeout=3,
    cache=cache,
)

while True:
    arm_holding_object = None
    text, cache = wait_for_event(id="text", timeout=0.3, cache=cache)
    if stop:
        continue
    values, cache = wait_for_event(id="pose", cache=cache)
    if values is None:
        continue
    values = values.to_numpy().reshape((-1, 6))
    if len(values) < 2:
        continue

    # 相机坐标系下的抓取位置
    obj = [values[0][0], values[0][1], values[0][2]]
    obj_x = values[0][0]
    # 相机坐标系下的抓取位置
    dest = [values[1][0], values[1][1], values[1][2]]

    target_arm, arm_holding_object = (
        ("r_arm", "right") if obj_x > 0.0 else ("l_arm", "left")
    )
    stage = "object"
    node.send_output(
        f"action_{target_arm}",
        pa.array(obj, type=pa.float64()),
        metadata={"encoding": "xyzrpy", "arm": arm_holding_object, "stage": stage},
    )
    _, cache = wait_for_event(id=f"response_{target_arm}", cache=cache)

    stage = "destination"
    node.send_output(
        f"action_{target_arm}",
        pa.array(dest, type=pa.float64()),
        metadata={"encoding": "xyzrpy", "arm": arm_holding_object, "stage": stage},
    )
    _, cache = wait_for_event(id=f"response_{target_arm}", cache=cache)

    # 结束一次流程
    stop = True

    if cache.get("finished", False):
        break
