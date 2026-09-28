import os
import sys
import json
import time
import lzma
import base64


INPUT_GGUF = r"Your GGUF path"
WORK_DIR = r"F:\AI代码"
OUTPUT_PY = os.path.join(WORK_DIR, "embedded_model.py")


COMPRESSED_BIN = os.path.join(WORK_DIR, "_embed_compressed.bin")
OUTPUT_TMP = os.path.join(WORK_DIR, "_embed_output.py.tmp")
STATE_FILE = os.path.join(WORK_DIR, "_embed_state.json")

LZMA_PRESET = 9 | lzma.PRESET_EXTREME    
READ_CHUNK = 3 * 1024 * 1024           
LINE_BYTES = 8000                         
STATE_SAVE_INTERVAL = 20                    

HEADER = (
    "# 此文件由 AI压缩.py 自动生成，请勿手动编辑\n"
    "MODEL_B85_DATA = (\n"
)
FOOTER = ")\n"


def human_size(n):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


def print_progress(prefix, current, total, extra=""):
    width = 40
    pct = current / total if total > 0 else 0
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    line = (
        f"\r{prefix} [{bar}] {pct*100:5.1f}%  "
        f"{human_size(current)}/{human_size(total)} {extra}"
    )
    sys.stdout.write(line)
    sys.stdout.flush()


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)


def clear_state():
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)


def stage_compress():
    print("\n=== 阶段 1/2：LZMA 压缩 ===")

    if os.path.exists(COMPRESSED_BIN) and os.path.getsize(COMPRESSED_BIN) > 0:
        size = os.path.getsize(COMPRESSED_BIN)
        print(f"发现已有的压缩文件：{COMPRESSED_BIN}（{human_size(size)}）")
        ans = input("是否复用？（Y/n） ").strip().lower()
        if ans in ("", "y", "yes"):
            return
        os.remove(COMPRESSED_BIN)

    if not os.path.exists(INPUT_GGUF):
        print(f"[错误] 找不到输入文件：{INPUT_GGUF}")
        sys.exit(1)

    total = os.path.getsize(INPUT_GGUF)
    print(f"输入：{INPUT_GGUF}")
    print(f"大小：{human_size(total)}")
    print("压缩中（LZMA 最高级别，速度较慢）...\n")

    t0 = time.time()
    tmp_bin = COMPRESSED_BIN + ".tmp"

    with open(INPUT_GGUF, "rb") as fin, open(tmp_bin, "wb") as fout:
        comp = lzma.LZMACompressor(preset=LZMA_PRESET)
        read = 0
        while True:
            chunk = fin.read(READ_CHUNK)
            if not chunk:
                break
            read += len(chunk)
            fout.write(comp.compress(chunk))
            print_progress("压缩中", read, total)
        fout.write(comp.flush())

    os.replace(tmp_bin, COMPRESSED_BIN)
    comp_size = os.path.getsize(COMPRESSED_BIN)
    print()
    print(
        f"压缩完成：{human_size(total)} -> {human_size(comp_size)} "
        f"（节省 {100 * (1 - comp_size / total):.1f}%），耗时 {time.time() - t0:.1f}s"
    )

    clear_state()
    if os.path.exists(OUTPUT_TMP):
        os.remove(OUTPUT_TMP)



def stage_encode():
    print("\n=== 阶段 2/2：Base85 编码并写入 Python 文件 ===")

    if not os.path.exists(COMPRESSED_BIN) or os.path.getsize(COMPRESSED_BIN) == 0:
        print("[错误] 压缩文件不存在，请先运行阶段 1")
        sys.exit(1)

    comp_size = os.path.getsize(COMPRESSED_BIN)
    state = load_state()
    lines_done = state.get("lines_done", 0)
    output_size = state.get("output_size", 0)

    if lines_done == 0:

        with open(OUTPUT_TMP, "wb") as f:
            f.write(HEADER.encode("utf-8"))
        output_size = len(HEADER.encode("utf-8"))
    else:

        if not os.path.exists(OUTPUT_TMP):
            print(f"[警告] 状态显示已完成 {lines_done} 行，但临时输出不存在，将从头开始")
            lines_done = 0
            with open(OUTPUT_TMP, "wb") as f:
                f.write(HEADER.encode("utf-8"))
            output_size = len(HEADER.encode("utf-8"))
        else:
            actual = os.path.getsize(OUTPUT_TMP)
            if actual != output_size:
                with open(OUTPUT_TMP, "r+b") as f:
                    f.truncate(output_size)
                print(f"输出文件已回退：{human_size(actual)} -> {human_size(output_size)}")
            print(f"检测到中断进度：已完成 {lines_done} 行，从 {human_size(lines_done * LINE_BYTES)} 继续\n")


    t0 = time.time()
    fout = open(OUTPUT_TMP, "ab")
    try:
        with open(COMPRESSED_BIN, "rb") as fin:
            fin.seek(lines_done * LINE_BYTES)
            while True:
                chunk = fin.read(LINE_BYTES)
                if not chunk:
                    break

                b85 = base64.b85encode(chunk).decode("ascii")
                line = "    " + json.dumps(b85) + "\n"
                fout.write(line.encode("utf-8"))

                lines_done += 1
                output_size = fout.tell()

                if lines_done % STATE_SAVE_INTERVAL == 0:
                    fout.flush()
                    save_state({"lines_done": lines_done, "output_size": output_size})

                processed = min(lines_done * LINE_BYTES, comp_size)
                print_progress("编码中", processed, comp_size)
    finally:
        fout.close()


    with open(OUTPUT_TMP, "ab") as f:
        f.write(FOOTER.encode("utf-8"))

    print()
    print(f"编码完成，耗时 {time.time() - t0:.1f}s")


    if os.path.exists(OUTPUT_PY):
        backup = OUTPUT_PY + ".bak"
        if os.path.exists(backup):
            os.remove(backup)
        os.replace(OUTPUT_PY, backup)
    os.replace(OUTPUT_TMP, OUTPUT_PY)

    print(f"已生成：{OUTPUT_PY}（{human_size(os.path.getsize(OUTPUT_PY))}）")


    clear_state()



def main():
    print("=" * 60)
    print("GGUF -> LZMA -> Base85 -> Python 代码")
    print("=" * 60)

    stage_compress()
    stage_encode()

    print("\n全部完成！")
    print(f"生成的 Python 文件：{OUTPUT_PY}")
    print("使用方式：from embedded_model import MODEL_B85_DATA")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[中断] 进度已保存。再次运行本脚本即可继续。")
        sys.exit(130)
