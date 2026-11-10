"""Verify the shipped fixture bytes without contacting services or the model."""
import hashlib
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
manifest = json.loads((root / 'checksums.json').read_text(encoding='utf-8'))
if manifest.get('version') != 1 or manifest.get('text_normalization') != 'CRLF to LF':
    sys.exit('不支持的样例校验清单。')
failed = False
for relative, expected in sorted(manifest['files'].items()):
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        print(f'缺失或路径无效: {relative}')
        failed = True
        continue
    data = path.read_bytes()
    if path.suffix in {'.txt', '.json'}:
        data = data.replace(b'\r\n', b'\n')
    actual = hashlib.sha256(data).hexdigest()
    ok = actual == expected
    print(f'{"通过" if ok else "不匹配"}: {relative}')
    failed |= not ok
sys.exit(1 if failed else 0)
