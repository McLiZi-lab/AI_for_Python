import base64
import lzma
import os
import sys
import time
from embedded_model import MODEL_B85_DATA
from llama_cpp import Llama

# ===== 配置 =====
TMP_GGUF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_runtime_model.gguf")
N_CTX = 2048
MAX_TOKENS = 256
TEMPERATURE = 0.7
TOP_P = 0.9
REPEAT_PENALTY = 1.1


def prepare_gguf():
    """从 embedded_model.py 还原出 gguf 文件，已存在则复用。"""
    print("1. 检查临时 gguf ...")
    if os.path.exists(TMP_GGUF):
        print(f"   已存在：{TMP_GGUF}（{os.path.getsize(TMP_GGUF) / 1024 / 1024:.1f} MB），直接复用")
        return

    print("2. Base85 解码 ...")
    t = time.time()
    compressed_data = base64.b85decode(MODEL_B85_DATA)
    print(f"   压缩数据：{len(compressed_data) / 1024 / 1024:.1f} MB，耗时 {time.time()-t:.2f}s")

    print("3. LZMA 解压 ...")
    t = time.time()
    raw_data = lzma.decompress(compressed_data)
    print(f"   原始 GGUF：{len(raw_data) / 1024 / 1024:.1f} MB，耗时 {time.time()-t:.2f}s")

    print(f"4. 写入临时文件：{TMP_GGUF}")
    t = time.time()
    with open(TMP_GGUF, "wb") as f:
        f.write(raw_data)
    print(f"   写入完成，耗时 {time.time()-t:.2f}s")

    del raw_data, compressed_data


def load_model():
    print("5. 加载 Llama 模型 ...")
    t = time.time()
    llm = Llama(
        model_path=TMP_GGUF,
        n_ctx=N_CTX,
        verbose=False,
    )
    print(f"   加载完成，耗时 {time.time()-t:.2f}s")
    return llm


def chat_loop(llm):
    print()
    print("=" * 60)
    print("进入问答模式。输入问题后回车；输入 exit / quit / q 退出。")
    print("输入 clear 清空对话历史，重新开始。")
    print("=" * 60)

    messages = [
        {"role": "system", "content": "You are a helpful assistant. Answer concisely."}
    ]

    while True:
        try:
            user_input = input("\n你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break

        if not user_input:
            continue

        cmd = user_input.lower()
        if cmd in ("exit", "quit", "q"):
            print("再见。")
            break
        if cmd == "clear":
            messages = [
                {"role": "system", "content": "You are a helpful assistant. Answer concisely."}
            ]
            print("对话历史已清空。")
            continue

        messages.append({"role": "user", "content": user_input})

        print("AI > ", end="", flush=True)
        t = time.time()
        try:
            output = llm.create_chat_completion(
                messages=messages,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                top_p=TOP_P,
                repeat_penalty=REPEAT_PENALTY,
                stream=True,
            )

            reply = ""
            for chunk in output:
                delta = chunk["choices"][0].get("delta", {})
                piece = delta.get("content", "")
                if piece:
                    reply += piece
                    sys.stdout.write(piece)
                    sys.stdout.flush()
            print()
            elapsed = time.time() - t
            print(f"[耗时 {elapsed:.2f}s，共 {len(reply)} 字符]")

        except Exception as e:
            print(f"\n[出错] {e}")
            # 出错时把本轮 user 消息移除，避免污染历史
            messages.pop()
            continue

        messages.append({"role": "assistant", "content": reply})

        # 控制历史长度，避免超出上下文
        # 简单策略：只保留 system + 最近 6 轮对话
        if len(messages) > 13:
            messages = [messages[0]] + messages[-12:]


def main():
    prepare_gguf()
    llm = load_model()
    chat_loop(llm)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中断。")
