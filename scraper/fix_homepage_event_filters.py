#!/usr/bin/env python3
"""Repair the homepage event filters so date tabs use real date windows.

Historically the homepage tagged every event held on any Saturday or Sunday as
"weekend". That made the This weekend tab show events months away. This script
is intentionally idempotent and patches the hand-authored homepage shell.
The accompanying workflow applies it immediately and can be rerun safely.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = ROOT / "index.html"

OLD = '''function eventTagsForStory(story){
  const tags = new Set(["upcoming"]);
  const start = storyEventStart(story);
  if(start){
    const d = new Date(start);
    const now = new Date();
    if(d.toDateString() === now.toDateString()) tags.add("tonight");
    if(d.getDay() === 0 || d.getDay() === 6) tags.add("weekend");
  }
'''

NEW = '''function eventTagsForStory(story){
  const tags = new Set(["upcoming"]);
  const start = storyEventStart(story);
  if(start){
    const d = new Date(start);
    const now = new Date();
    const today = new Date(now);
    today.setHours(0,0,0,0);
    if(d.toDateString() === now.toDateString()) tags.add("tonight");

    // "This weekend" means the current or next Saturday-and-Sunday window,
    // not every future event that happens to fall on a weekend.
    const day = today.getDay();
    const daysToSaturday = day === 0 ? -1 : day === 6 ? 0 : 6 - day;
    const weekendStart = new Date(today);
    weekendStart.setDate(weekendStart.getDate() + daysToSaturday);
    const weekendEnd = new Date(weekendStart);
    weekendEnd.setDate(weekendEnd.getDate() + 2);
    if(d >= weekendStart && d < weekendEnd) tags.add("weekend");
  }
'''


def main() -> int:
    page = HOME.read_text(encoding="utf-8")
    if NEW in page:
        print("homepage event filters: already fixed")
        return 0
    if OLD not in page:
        raise SystemExit("homepage event filter block not found; refusing unsafe edit")
    HOME.write_text(page.replace(OLD, NEW, 1), encoding="utf-8")
    print("homepage event filters: fixed real weekend window")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
