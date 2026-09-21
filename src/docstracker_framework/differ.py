import difflib
from docstracker_framework.models import Page, NewPage, ModifiedPage, SectionDiff


class Differ:
    def diff(self, current: Page, previous: Page | None) -> NewPage | ModifiedPage | None:
        if previous is None:
            return NewPage(page=current)

        prev_by_heading = {s.heading: s for s in previous.sections}
        curr_by_heading = {s.heading: s for s in current.sections}

        section_diffs = []
        for heading, curr_section in curr_by_heading.items():
            prev_section = prev_by_heading.get(heading)
            if prev_section is None:
                section_diffs.append(SectionDiff(
                    heading=heading,
                    added=curr_section.body.splitlines(),
                    removed=[],
                ))
                continue
            if curr_section.body == prev_section.body:
                continue
            added = [
                line[2:] for line in difflib.ndiff(
                    prev_section.body.splitlines(),
                    curr_section.body.splitlines(),
                ) if line.startswith("+ ")
            ]
            removed = [
                line[2:] for line in difflib.ndiff(
                    prev_section.body.splitlines(),
                    curr_section.body.splitlines(),
                ) if line.startswith("- ")
            ]
            section_diffs.append(SectionDiff(heading=heading, added=added, removed=removed))

        for heading, prev_section in prev_by_heading.items():
            if heading not in curr_by_heading:
                section_diffs.append(SectionDiff(
                    heading=heading,
                    added=[],
                    removed=prev_section.body.splitlines(),
                ))

        if not section_diffs:
            return None
        return ModifiedPage(page=current, diffs=section_diffs)
