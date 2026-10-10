"""Generate anonymous test fixtures; never read documents from the workstation."""
import json
import sys
from pathlib import Path

from tests.generate_fixtures import generate

root = Path(sys.argv[1]).resolve()
root.mkdir(parents=True, exist_ok=True)
config = generate(root / 'synthetic-fixtures')
(root / 'fixtures.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
print('Synthetic fixtures prepared; no personal documents were accessed.')
