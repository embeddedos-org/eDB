"""Generate narration audio using Google Text-to-Speech."""
from gtts import gTTS

NARRATION = (
    "Introducing eDB. A unified multi-model database ecosystem. Feature one: Supports relational, document, and graph models in a single engine. Feature two: Real-time replication keeps your data consistent across nodes. Feature three: Embedded SQL engine runs directly inside your application. eDB. Open source and blazing fast. Visit github dot com slash embeddedos-org slash eDB."
)

tts = gTTS(text=NARRATION, lang="en", slow=False)
tts.save("narration.mp3")
print(f"Generated narration.mp3 ({len(NARRATION)} chars)")
