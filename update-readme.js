const fs = require('fs');

// 1. Define your updated content (or fetch it via GitHub API)
const latestRoadmap = `- [x] Phase 1: MVP\n- [/] Phase 2: Beta Testing (In Progress)\n- [ ] Phase 3: Public Launch`;
const latestTimeline = `- Updated on ${new Date().toLocaleDateString()}: Deployed latest features.`;

// 2. Read the current README
let readme = fs.readFileSync('README.md', 'utf8');

// 3. Replace content between the tags
readme = readme.replace(
  /<!-- ROADMAP_START -->[\s\S]*<!-- ROADMAP_END -->/,
  `<!-- ROADMAP_START -->\n${latestRoadmap}\n<!-- ROADMAP_END -->`
);
readme = readme.replace(
  /<!-- TIMELINE_START -->[\s\S]*<!-- TIMELINE_END -->/,
  `<!-- TIMELINE_START -->\n${latestTimeline}\n<!-- TIMELINE_END -->`
);

// 4. Save the file
fs.writeFileSync('README.md', readme);
console.log('README updated successfully!');
