# Sandbox console visual update

The console retains its existing HTTP controls and adds a forest-green editorial
header, local artwork, consistent line icons, softer cards and restrained motion.
The artwork is decorative: it conveys no order or source status. Live values and
all failures continue to come from the existing APIs.

## Artwork

Generated with the built-in `image_gen` tool, then encoded as responsive local
WebP assets. No external image host, font service or animation library is required.

| Asset | Dimensions | Bytes |
|---|---|---|
| `app/static/images/commerce-atmosphere.webp` | 1920 × 640 | 75,550 |
| `app/static/images/commerce-atmosphere-small.webp` | 960 × 320 | 22,072 |

The generated PNG was 2,004,334 bytes. Encoding reduces the desktop transfer size
by about 96%. The mobile picture source and matching preload media query choose
the smaller asset at 760 pixels and below. The header has reserved geometry and
a solid-color fallback; image decoding is asynchronous. ETag conditional requests
return 304. Inventory space is reserved before data arrives to reduce layout shifts.

Final generation prompt:

> Use case: stylized-concept. Asset type: premium wide web dashboard background
> image for the existing DemoCommerce Sandbox, a fake ecommerce HTTP source
> testing console with forest-green branding. Create one high-quality cinematic
> editorial 3D still-life image, panoramic wide composition approximately 3:1.
> Scene: abstract architectural studio with deep forest-green walls, sage stone
> platforms, elegant unbranded kraft-paper shipping parcels, one neatly folded
> packing carton, an abstract frosted-glass arch and a few subtle brass
> logistics-inspired curves. Group the objects in the rightmost 40 percent,
> leaving the left 60 percent calm dark green negative space for legible interface
> text. Refined tactile materials, realistic paper fibers and matte mineral
> surfaces, soft warm sunlight from upper right, delicate soft shadows, subtle
> depth, carefully art-directed luxury product photography aesthetic, restrained
> cream/sage/emerald palette matching forest-green UI. Beautiful and sophisticated
> rather than cartoonish. This is the background asset only, no UI mockup. No text,
> no letters, no logos, no watermark, no people, no readable labels, no busy
> graphics, no glowing cyberpunk elements. Ensure the right-side objects remain
> recognizable when cropped into a shallow banner.

## Interaction

- View transitions use a 170-ms opacity/transform animation. Button and input
  feedback uses 150-ms transitions. No scroll-linked or JavaScript animation loop.
- Switching views returns to the top with native smooth scrolling. Reduced-motion
  preferences disable animated scrolling, transitions and loading pulses.
- Navigation exposes `aria-pressed`; decorative artwork/icons are hidden from
  assistive technology. The connection badge reports pending/success/error states.
- Inputs retain visible focus feedback. Source result text remains readable on
  opaque surfaces; background art appears only in the common header.

## Validation

Actual browser checks confirmed desktop artwork at natural width 1920, mobile
artwork at natural width 960, successful decoding, and no horizontal overflow in
any of the four views at a 390-pixel viewport. Independent S08 504 responses and
bound simulated replies were exercised again after the visual update.
The final preview was reset to the original baseline.

Run the Python suite, Ruff checks, real HTTP smoke and
`node --test tests/console_behavior.test.cjs`. The added HTTP test verifies local
artwork media types, WebP signatures, size budgets and conditional caching; the
added JavaScript test verifies accessible view state and reduced-motion scrolling.
