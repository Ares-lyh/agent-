"""Resolve explicit direction before references; feedback can refine a new take."""
import re
from src.models.vocals import VocalRequirements


def positive_text(text):
    # Excluded voices must not be mistaken for a requested duet.
    text = re.sub(r"(?:实际|当前|现在|成品|音频|生成的|听起来)(?:是|为|仍是|唱成了|听着像)\s*(?:男声|女声)", "", text)
    return re.sub(r"(?:不要|禁止|不得|避免|排除|不使用)[^，,。;；\n]*|\b(?:no|without|not)\s+(?:male|female)\s*(?:vocals?|voice|singer)?", "", text, flags=re.I)


def lead_from_text(text):
    directions = re.findall(r"(?:改为|改成|只要|只用|请用)[^，,。;；\n]{0,12}?(男女对唱|女声|男声)", text)
    if directions:
        return {"女声": "female", "男声": "male", "男女对唱": "mixed"}[directions[-1]]
    text = positive_text(text)
    female = bool(re.search(r"女声|女歌手|\bfemale\b|\bsoprano\b", text, re.I))
    male = bool(re.search(r"男声|男歌手|\bmale\b|\bbaritone\b", text, re.I))
    if re.search(r"男女对唱|男女合唱|\bduet\b", text, re.I) or female and male:
        return "mixed"
    return "female" if female else "male" if male else "unspecified"


def resolve_vocals(brief, feedback=None):
    references = "；".join([*brief.references, *brief.constraints, brief.mood])
    result = (brief.vocals.model_copy(deep=True) if brief.vocals else
              VocalRequirements(lead=lead_from_text(references), source="references"))
    if brief.vocals:
        result.source = "brief"
    if feedback:
        requested = lead_from_text(feedback)
        if requested != "unspecified":
            result.lead = requested
            result.source = "feedback"
    text = positive_text((feedback or "") + "；" + references)
    if re.search(r"空灵|ethereal|airy", text, re.I):
        result.style = (result.style + " 空灵、轻盈、气声、清晰中文咬字，高潮仍保留轻盈音色。").strip()
    if result.lead == "unspecified" and not result.style:
        result.source = "unspecified"
    return result
