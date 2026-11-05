"""PDF 텍스트 추출의 격리 경계. stdin/stdout만 쓰며 원문·오류를 파일·로그에 남기지 않는다."""

import json
import logging
from pathlib import Path
import sys

import yaml


def main() -> int:
    limits = yaml.safe_load((Path(__file__).resolve().parents[3] / "config/lab_pdf.yaml").read_text(encoding="utf-8"))["limits"]
    try:
        import resource
        memory = limits["memory_megabytes"] * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (limits["timeout_seconds"], limits["timeout_seconds"]))
        from app.demo_server import block_outbound_sockets
        block_outbound_sockets()
        from io import BytesIO
        from pypdf import PdfReader
        logging.disable(logging.CRITICAL)
        data = sys.stdin.buffer.read(limits["maximum_upload_bytes"] + 1)
        if len(data) > limits["maximum_upload_bytes"] or not data.startswith(b"%PDF-"):
            return 2
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted or len(reader.pages) > limits["maximum_pages"]:
            return 2
        parts = []
        size = 0
        for page in reader.pages:
            content = page.extract_text(extraction_mode="layout") or ""
            size += len(content)
            if size > limits["maximum_text_characters"]:
                return 2
            parts.append(content)
        if not any(part.strip() for part in parts):
            return 2
        sys.stdout.write(json.dumps({"text": "\n".join(parts)}))
        return 0
    except Exception:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
