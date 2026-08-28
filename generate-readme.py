import os
import datetime

# 1. Define your dynamic content
# (In a real setup, you could read this from a 'roadmap.txt' or fetch it via GitHub's API)
current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
latest_timeline = f"- **Last System Update:** {current_time} (Automated via GitHub Actions)\n- Added new automated tracking features."
latest_roadmap = "- [x] Phase 1: Core Automation\n- [/] Phase 2: Dynamic API Syncing (In Progress)\n- [ ] Phase 3: Analytics Dashboard"

# 2. Read the existing README
with open("README.md", "r", encoding="utf-8") as file:
    readme = file.read()

# 3. Helper function to swap content between target tags
def update_section(content, start_tag, end_tag, new_text):
    start_idx = content.find(start_tag)
    end_idx = content.find(end_tag)
    if start_idx == -1 or end_idx == -1:
        return content
    return content[:start_idx + len(start_tag)] + "\n" + new_text + "\n" + content[end_idx:]

# 4. Inject the new sections
readme = update_section(readme, "<!-- ROADMAP_ZONE_START -->", "<!-- ROADMAP_ZONE_END -->", latest_roadmap)
readme = update_section(readme, "<!-- TIMELINE_ZONE_START -->", "<!-- TIMELINE_ZONE_END -->", latest_timeline)

# 5. Write the changes back to the README
with open("README.md", "w", encoding="utf-8") as file:
    file.write(readme)

print("README text updated successfully!")
