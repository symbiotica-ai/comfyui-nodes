# ABOUTME: The Hypereel UGC preset catalogs (styles, hooks, settings) ported verbatim
# ABOUTME: from the platform's ugc-presets.ts — data only, plus the notes-block builder.

STYLES = {
    "UGC": 'Style: UGC creator video, handheld iPhone, vertical 9:16 — this anchor phrase opens the prompt. Look line for the end of the prompt: slightly handheld, natural window light, the warm faintly oversaturated look of a good phone camera, no studio polish. Never use cinema vocabulary (cinematic, jib, crane, steadicam) anywhere.',
    "Get Ready With Me": 'Style: UGC, get ready with me, iPhone front camera, fashion vlog, playful energy. The creator films themselves getting ready while talking about the product.',
    "Selfie Testimonial": 'Style: authentic selfie-style testimonial — the creator holds the phone at arm’s length and speaks honestly to camera about the product, casual and personal.',
    "Direct to Camera": 'Style: creator speaking straight to camera, framed like a front-camera monologue, confident and direct, product held up at key moments.',
    "Addiction": 'Style: can’t-put-it-down product obsession — the creator keeps getting pulled back to the product mid-sentence, playing it "just one more time", laughing at themselves.',
    "Secret Hack Reveal": 'Style: the creator leans in conspiratorially and reveals a clever hack/trick involving the product, like sharing a secret with the viewer.',
    "Couple Sharing": 'Style: a couple at home sharing the product — playful back-and-forth, one shows it off while the other reacts, warm domestic energy.',
    "Tutorial": 'Style: step-by-step tutorial — the creator walks through using the product in clear stages, pointing at the screen/product, helpful and energetic.',
    "Product Review": 'Style: authentic product review — the creator gives an honest, structured take: what it is, what they liked, a verdict with a recommendation.',
    "Before & After": 'Style: before & after transformation — the video contrasts life/results without the product vs with it, with a clear reveal moment.',
    "Unboxing": 'Style: high-quality unboxing — the creator opens the product on camera, savoring the reveal, close-ups on details, genuine first reactions.',
    "Wild Card": 'Style: a unique, creative, unexpected video concept — surprising framing or scenario, but the product stays the hero throughout.',
    "Streamer": 'Style: authentic live-stream clip in the classic vertical stream layout, WITH snappy UGC editing. The frame is HARD-SPLIT into two stacked regions: the TOP ~40% is the creator’s facecam, the BOTTOM ~60% is THE GAME being played, filling the region with its live HUD — when gameplay footage @Video1 is provided use exactly that footage; otherwise render the game IN MOTION exactly from the screenshot references (characters moving, taps landing, numbers ticking — ignore any marketing caption text baked into the screenshots, show the game interface itself). DEVICE COHERENCE: the creator plays on the device the game actually runs on — for a MOBILE game the phone is in her hands or mounted below the camera, eyes mostly DOWN on the phone, glancing UP only to react and talk to chat. Background: NO desktop monitors, NO other games. EDITING: hard jump cuts between beats, quick push-in zooms on facecam reactions, occasional snap zoom-out to reframe — energetic clipped-stream pacing, while the split layout stays consistent.',
    "Gadget Saved Me": 'Style: creator-led recommendation — a small everyday problem plays out, then the product steps in and saves the moment; the creator turns the features into a personal story.',
}

HOOKS = {
    "Spicy Tease": 'Hook (SPICY, realize it FRESH each run — do not repeat a fixed shot): open on a genuinely scroll-stopping, flirtatious, suggestive-but-tasteful moment that draws the eye, chosen to fit THIS creator, product and setting. Pull from a range and pick what fits: a slow confident reveal, a knowing look back over the shoulder, a lean-in toward the lens with a teasing half-smile, a playful lip bite, an alluring stretch or hair-flip, a low-angle full-body beat, an unexpected reveal of the product held close. Vary the framing and the wording every time; never default to a lips or mouth close-up. Open with a line that feels a little forbidden, too-honest, or intimately confessional, in her voice. Keep it platform-safe and SFW (no explicit or revealing content) while still being the kind of frame someone stops scrolling for.',
    "Shock Stat": 'Hook (use as Shot 1): Static phone propped on a kitchen counter, medium close-up. The creator sets her phone down flat on the counter with a firm tap, eyes widening, and stares straight into the lens. She says in a flat, stunned tone: "Four hundred dollars. Every single month. Gone." Line shape: one concrete number about the problem, delivered in short fragments.',
    "POV Discovery": 'Hook (use as Shot 1): Handheld iPhone, close-up on the creator’s right hand picking the product up off a cluttered desk, then the camera tilts up to her face. Her eyebrows rise and her mouth opens slightly. She says in a hushed, disbelieving tone: "Wait. Why did nobody tell me about this?" Line shape: a why-did-nobody-tell-me question.',
    "Whisper Secret": 'Hook (use as Shot 1): Handheld selfie framing, close-up, shoulders up. The creator glances once to her left, leans closer to the lens, and cups her left hand beside her mouth. She whispers: "Okay. Do not tell anyone I shared this." Line shape: a whispered do-not-tell confidence. Quiet room tone.',
    "Rant Energy": 'Hook (use as Shot 1): Phone propped upright on a coffee table, medium shot. The creator drops onto the couch, exhales hard through her nose, and makes one deliberate open-palm gesture toward the lens. She says in an exasperated, rising tone: "I am so tired of overpaying for this." Line shape: an I-am-done complaint naming the pain point.',
    "Duet Reaction": 'Hook (use as Shot 1): Static vertical frame split — the app screenshot fills the upper half, the creator sits in the lower half in a bedroom. She points up at the screenshot with one finger, jaw dropping open. She says in a loud, incredulous tone: "There is no way this is real." Line shape: a no-way-this-is-real challenge.',
    "Deadpan Comedy": 'Hook (use as Shot 1): Static phone propped at eye level, medium close-up, plain wall behind. The creator sits completely still, shoulders level, face expressionless, gaze locked on the lens without blinking. She says in a flat monotone: "So this fixed my entire life. Anyway." Line shape: an oversized claim delivered with zero energy, clipped ending.',
    "FOMO Urgency": 'Hook (use as Shot 1): Handheld iPhone, slightly shaky, medium shot. The creator walks briskly toward the camera down a hallway, stops close to the lens, and glances once at her watch. She says in a hurried, breathless tone: "You have about two days before this is gone." Line shape: a concrete deadline addressed to the viewer. Never use the word "fast" — use brisk or hurried.',
    "Cozy Authentic": 'Hook (use as Shot 1): Static phone propped on a windowsill, soft morning window light, medium close-up. The creator sits wrapped in a knit blanket, cradles a mug in both hands, takes a slow sip, and gives a small sleepy half-smile. She says in a warm, unhurried tone: "Slow morning. But I have to show you something." Line shape: a gentle low-stakes invitation.',
    "Bedroom": 'Setting: on the bed or propped against pillows, soft window light, unmade bed and cozy textures. Relaxed wind-down vibe — honest, low-effort feel. No desk or monitors.',
}

SETTINGS = {
    "Bathroom": 'Setting: mirror selfie / front camera in a bathroom, ring-light or vanity lighting, tiles visible. Intimate getting-ready energy — the product shown mid-routine, close-up friendly.',
    "Kitchen": 'Setting: standing at the counter or leaning on the island, natural daylight, clean surface with a mug or fruit in the background. Casual mid-day energy.',
    "Office": 'Setting: desk setup, laptop open, coffee nearby, clean modern space with soft monitor glow. Hushed mid-workday tone — a quick product mention squeezed between tasks.',
    "Street": 'Setting: walking on a sidewalk or standing on an urban street, handheld selfie, city backdrop with storefronts and pedestrians. Energetic pace, talking while moving.',
    "In Car": 'Setting: selfie from the driver or passenger seat, parked, window light on the face. Casual tone — talking to camera between errands.',
    "Gym": 'Setting: gym floor or post-workout bench, bright overhead lighting, equipment in the background. Freshly-finished energy — the product tied to performance or recovery.',
    "Gamer Room": 'Setting: aesthetic creator room — mirror, clothes, RGB gaming setup glowing in the background, soft natural daylight, slight creative mess.',
    "Volcano Rim": 'Setting: the creator sits on the rim of an active volcano, lava bubbling below, smoke drifting through frame — and delivers a totally casual product review with zero reaction to the danger.',
    "Airplane Wing": 'Setting: the creator sits on an airplane wing mid-flight — powerful wind, clouds, engine roar — casually reviewing the product.',
    "Tiny Reviewer": 'Setting: the creator is shrunk to 15cm tall next to the product at full size, leaning on it and delivering a normal selfie review at an impossible scale.',
    "Nature": 'Setting: outdoors — a trail, park, beach, or garden. Natural light, greenery or open sky. Active or peaceful mood adapting to the product.',
    "Roofing": 'Setting: the creator stands on the edge of a skyscraper rooftop, city skyline stretching behind them, wind in their hair — delivering a completely casual selfie review at dizzying height.',
    "Car Roof": 'Setting: the creator sits on the roof of a moving car on a desert highway at golden hour, swaying with the road while reviewing the product; a semi truck passes — no flinch.',
    "Train Surf": 'Setting: the creator hangs off the side of a moving train filming a selfie — the wind pressing against them is the live demo while they review the product.',
    "Streamer Girl": 'A stylized 3D-rendered young female game streamer at her gaming setup, headphones around her neck, soft RGB glow behind her, casual top, looking at the webcam with a bright expressive face, portrait facecam framing. Clean polished digital-render character look, clearly NOT a real photograph. No text anywhere in the image.',
}


def build_notes(style, hook, setting):
    """The pre-labeled block the script LLM consumes after the product summary."""
    return (f"STYLE NOTE: {STYLES[style]}\n"
            f"HOOK PATTERN: {HOOKS[hook]}\n"
            f"SETTING NOTE: {SETTINGS[setting]}")
