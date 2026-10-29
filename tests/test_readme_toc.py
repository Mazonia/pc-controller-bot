"""
Test to verify that all Table of Contents anchor links in README.md point to valid targets.
"""

import re
from pathlib import Path

def test_readme_table_of_contents_anchors():
    readme_path = Path(__file__).resolve().parent.parent / "README.md"
    assert readme_path.exists(), "README.md not found"
    
    content = readme_path.read_text(encoding="utf-8")
    toc_match = re.search(r"## 📑 Table of Contents.*?(?=---)", content, re.DOTALL)
    assert toc_match, "Table of Contents section not found in README.md"
    
    links = re.findall(r"\[([^\]]+)\]\(#([^\)]+)\)", toc_match.group(0))
    assert len(links) >= 15, f"Expected at least 15 TOC links, found {len(links)}"
    
    missing = []
    for label, anchor in links:
        has_anchor_id = f'id="{anchor}"' in content or f"id='{anchor}'" in content
        if not has_anchor_id:
            missing.append(f"{label} -> #{anchor}")
            
    assert not missing, f"Missing target anchors in README.md: {missing}"

