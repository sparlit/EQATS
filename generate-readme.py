from typing import Any
import os
import datetime
current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
latest_timeline = f'- **Last System Update:** {current_time} (Automated via GitHub Actions)\n- Added new automated tracking features.'
latest_roadmap = '- [x] Phase 1: Core Automation\n- [/] Phase 2: Dynamic API Syncing (In Progress)\n- [ ] Phase 3: Analytics Dashboard'
with open('README.md', 'r', encoding='utf-8') as file:
    readme = file.read()

def update_section(content: Any, start_tag: Any, end_tag: Any, new_text: Any) -> Any:
    start_idx = content.find(start_tag)
    end_idx = content.find(end_tag)
    if start_idx == -1 or end_idx == -1:
        return content
    return content[:start_idx + len(start_tag)] + '\n' + new_text + '\n' + content[end_idx:]
readme = update_section(readme, '<!-- ROADMAP_ZONE_START -->', '<!-- ROADMAP_ZONE_END -->', latest_roadmap)
readme = update_section(readme, '<!-- TIMELINE_ZONE_START -->', '<!-- TIMELINE_ZONE_END -->', latest_timeline)
with open('README.md', 'w', encoding='utf-8') as file:
    file.write(readme)
print('README text updated successfully!')
