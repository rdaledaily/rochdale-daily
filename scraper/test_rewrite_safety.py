from rewrite_safety import excessive_source_overlap

source = (
    "Rochdale Council has announced that Manchester Road will close from "
    "Monday morning while engineers repair a damaged section of carriageway. "
    "The closure is expected to remain in place until Friday afternoon."
)

copied = (
    "Manchester Road will close from Monday morning while engineers repair "
    "a damaged section of carriageway. The closure is expected to remain in "
    "place until Friday afternoon."
)

original = (
    "Drivers are being advised to plan another route next week because repair "
    "work will shut part of Manchester Road. Council engineers expect the work "
    "to continue for most of the working week."
)

assert excessive_source_overlap(copied, source)
assert not excessive_source_overlap(original, source)
assert not excessive_source_overlap(
    "The road will not be open on Monday.",
    "Road closed on Monday.",
)

print("Rewrite-safety regression tests passed.")
