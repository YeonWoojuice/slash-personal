"""Transport와 무관한 요약 입력 정규화와 프롬프트 생성."""


class SummaryInputTooShort(ValueError):
    def __init__(self, *, actual: int, minimum: int) -> None:
        self.actual = actual
        self.minimum = minimum
        super().__init__(f"요약할 만큼 긴 글이 아니다 ({actual}자, 최소 {minimum}자).")


def prepare_summary_text(text: str, *, minimum: int, maximum: int) -> str:
    normalized = text.strip()[:maximum]
    character_count = 0
    for character in normalized:
        if character.isspace():
            continue
        character_count += 1
        if character_count >= minimum:
            break
    if character_count < minimum:
        raise SummaryInputTooShort(actual=character_count, minimum=minimum)
    return normalized


def build_summary_prompt(text: str) -> str:
    return (
        "다음 글을 한국어로 요약해라.\n"
        "- 원문보다 짧게 쓴다\n"
        "- 최대 3문장\n"
        "- 요약문만 출력하고 다른 말은 붙이지 않는다\n"
        "- 원문에 없는 내용은 지어내지 않는다\n\n"
        f"{text}"
    )
