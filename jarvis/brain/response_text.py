"""Extract final text; private reasoning channels never enter UI, storage or TTS."""

import re

TAGS = ("<think>", "</think>", "<analysis>", "</analysis>", "<reasoning>", "</reasoning>")


class FinalTextFilter:
    """Handle reasoning tags even when the server splits them across chunks."""

    def __init__(self):
        self.pending = ""
        self.depth = 0
        self.discarded_characters = 0

    def feed(self, content: str) -> str:
        self.pending += content
        result = []
        while self.pending:
            if self.pending.startswith("<"):
                end = self.pending.find(">")
                if end == -1:
                    if any(tag.startswith(self.pending.casefold()) for tag in TAGS):
                        break
                    # A malformed reasoning tag fails closed instead of becoming speech.
                    if any(self.pending.casefold().startswith(prefix) for prefix in ("<think", "<analysis", "<reasoning")):
                        self.discarded_characters += len(self.pending)
                        self.pending = ""
                        self.depth = max(1, self.depth)
                        break
                    segment, self.pending = self.pending[0], self.pending[1:]
                else:
                    segment, self.pending = self.pending[:end + 1], self.pending[end + 1:]
                    match = re.fullmatch(r"<\s*(/?)\s*(think|analysis|reasoning)\s*>", segment, flags=re.IGNORECASE)
                    if match:
                        self.depth = max(0, self.depth - 1) if match[1] else self.depth + 1
                        self.discarded_characters += len(segment)
                        continue
            else:
                end = self.pending.find("<")
                end = end if end >= 0 else len(self.pending)
                segment, self.pending = self.pending[:end], self.pending[end:]
            if self.depth:
                self.discarded_characters += len(segment)
            else:
                result.append(segment)
        return "".join(result)

    def finish(self) -> str:
        tail, self.pending = self.pending, ""
        if self.depth or any(tag.startswith(tail.casefold()) for tag in TAGS) and tail:
            self.discarded_characters += len(tail)
            return ""
        return tail


def final_text(text: str) -> str:
    extractor = FinalTextFilter()
    return (extractor.feed(text) + extractor.finish()).strip()
