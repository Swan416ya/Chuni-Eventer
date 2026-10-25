# Mate result-screen placement

This note records the runtime facts used by the editor. It intentionally does
not include or redistribute game assets.

Mate action dispatch is documented separately in
[`mate-action-types-reverse-engineering.md`](mate-action-types-reverse-engineering.md):
Types 2–15 correspond to the D–SSS+ score ranks, while Types 16–18 belong to
the Mate ROOM / MateGarden flow.

## Runtime transform

In the local CHUNITHM 2.50 executable, the `Mate.xml` parser stores `texSizeX`,
`texSizeY`, `posX`, `posY`, and `scaleX10000` as five separate integer fields
at offsets `+0x38` through `+0x48`. The XML naming and stock values establish
the scale convention (`6000` means `0.6`). A nearby `0.0001f` constant is used
in several unrelated epsilon checks, so it is not used as evidence by itself.
The stock Mate XML requests a `1024 x 1024` off-screen render target.

The active result layout
`data/surfboard/play/result/CHU_UI_Result_00_v10.srd` contains these relevant
TRS2 transforms:

- result control: position `(960, 540)`, scale `1.0`
- character container: position `(0, 0)`, scale `1.0`
- E-mote body: position `(650, 96)`, scale `0.85`

The matching `CIMG` record defines `C_emote_body` as a `1080 x 1080` image
with origin `(540, 540)`. Its centre is therefore `(1610, 636)`, and its final
visible rectangle is `(1151, 177, 918, 918)` after the cast scale. This is the
important second stage that a direct 960-to-1920 viewport conversion misses.

For a 1920 x 1080 result screen this gives:

```text
xmlUnitX      = (1080 / texSizeX) * 0.85
xmlUnitY      = (1080 / texSizeY) * 0.85
screenCenterX = 1610 + posX * xmlUnitX
screenCenterY =  636 + posY * xmlUnitY
screenWidth   = croppedSourceWidth  * (scaleX10000 / 10000) * xmlUnitX
screenHeight  = croppedSourceHeight * (scaleX10000 / 10000) * xmlUnitY
```

For the stock `1024 x 1024` target, both unit factors are exactly
`0.896484375`. The dynamic surface clips anything outside its 918 x 918 screen
rectangle; the preview applies the same clip.

As a concrete cross-check, installed `mate031005` uses `(posX, posY)=(1,-50)`,
scale `6000`, and an E-mote `screenSize` of `800 x 1080`. Its authored canvas
therefore appears at about `(1395.74, 300.71, 430.31, 580.92)`. The top is near
`y=301`, below the top HUD, rather than hidden behind it as in the old preview.

The application parses the installed SRD at runtime and falls back to these
values if the installed game has no compatible result layout.

## Mate ROOM / MateGarden

The user-facing label is `Mate ROOM`; the executable and SurfRide assets call
the scene `MateGarden`. `CHU_UI_MateGarden_00.srd` exposes a dedicated
`L_MateGarden_chara` layer with this chain:

```text
C_chara_control = (960, 540), scale 1.0
C_chara_head    = (0, 0),     scale 1.0
C_emote_body    = (0, 12),    scale 1.0
```

The matching `C_emote_body` definition is `1080 x 1080`, origin `(540,540)`.
Therefore Mate ROOM places its dynamic texture at centre `(960,552)` and screen
rectangle `(420,12,1080,1080)`. This is not the result transform: the same XML
model is centred in Mate ROOM and is exactly `1 / 0.85 = 1.17647` times the
result-screen size. The surface begins at `y=12`, so applying the result
surface's `y=177` clipping boundary to Mate ROOM incorrectly cuts off the top.

The preview switches between both scene transforms without changing the XML
values. A dotted rectangle marks the SurfRide dynamic-texture surface; a
dashed rectangle marks the E-mote authored/model canvas. The latter is not an
alpha bound: the current animation may occupy only part of it.

`Result_00` exposes two sibling casts at the same transform:
`C_chara_body` and `C_emote_body`. The game replaces/selects one of these slots;
a Mate result is not the normal character branch plus another character. The
preview therefore omits the `CHARACTER RANK` panel while showing a Mate.

The E-mote PSB has its own authored coordinate system. For example, the
installed `emote031005.emtbytes` declares `screenSize=800x1080`, origin `(0,0)`,
and model pixel-marker bounds independent of the 4096x2048 packed texture atlas.
Consequently:

- `texSizeX/Y` define the off-screen render target, not visible character size;
- `posX/Y` translate the E-mote origin;
- `scaleX10000 * 0.0001` uniformly scales authored model geometry;
- visible bounds depend on the current animation/model, not the packed atlas.

Generated GIF models are simpler: every union-cropped frame is authored with
its origin at the frame centre. Their generated PSB `screenSize` and
`pixelMarker` bounds are now replaced with that frame canvas too, so the preview
and runtime use the same model envelope instead of inheriting the donor's.

## Result foreground layers

The complete result is composed from more than the Mate background scene.
`CHU_UI_Result_01_v10.srd` declares separate layers for score, combo, chain,
clear state, judgement data, awards, rating, rank, player information and note
details. The preview loads the corresponding installed-game DDS atlases and
draws the relevant foreground after the Mate, matching the game's occlusion
order.

SurfRide's `NODE` records form a first-child / next-sibling tree (`0x3c` and
`0x3d`). The matching `TRS2` records are local transforms in node order. The
animation-set records (`ANMS`) select `A_score_loop` for the default Score Page
00; the large note-detail table is only displayed by Score Page 01.

An important detail is that a resolved cast translation is its authored pivot,
not automatically the centre of its source texture. For the result panels the
pivot is the top-left corner. The old preview incorrectly subtracted half the
atlas crop size a second time, moving the UI hundreds of pixels left/up.

Recovered default-page anchors used by the preview are:

```text
score base             = (960,478) + (0,-7) + (0,0) + (-644,-208) = (316,263)
skill/clear base       = (959,464) + (-98,75) + (-383,29) + (-162,-65) = (316,503)
max-combo base         = (959,464) + (192,75) + (-383,31) + (-147,-67) = (621,503)
judge label/number row = x 679 / 920, starting around y 686
rating base            = (960,402) + (138,236) + (0,0) + (-138,-238)
                         + (-37,168) = (923,568)
version OP base        = (960,574) + (138,235) + (0,0) + (-138,-238)
                         + (-37,168) = (923,739)
```

The rating/over-power base images contain 37 px of authored left padding, so
their first visible panel pixel is at `x=960`; the preview preserves that
distinction between cast pivot and visible bounds.

Displayed score/judgement numbers are representative preview values rather
than live player data. Atlas regions, occupied rectangles, and the occlusion
order are taken from the installed game. A cabinet photograph is useful as a
cross-check, but is not used as the coordinate source.

The score panel uses the default Page 00 score base plus its separate
`NEW RECORD` strip. Drawing the complete `Result_score` reference atlas as one
rectangle is invalid because that texture contains multiple slice/reference
parts, not a ready-to-display panel.

## XML fields and model differences

`texSizeX` and `texSizeY` are forwarded separately to the E-mote render target;
they are not the visible character bounds. Visible size depends on the model's
own authored canvas/parts and the XML scale.

For imported GIFs the converter controls the model geometry, unions the alpha
bounds across all frames, crops them, and therefore knows the exact visible
source size. The editor preview can use the formula above directly.

For arbitrary native PSB/E-mote models, bones, part transforms and animation can
move outside a texture's alpha bounds. Exact source bounds require the E-mote
runtime renderer. The editor therefore treats the XML coordinate transform as
exact but labels its native-model silhouette as an estimate.

## Donor `.emtbytes`

The donor is only a compatible PSB/E-mote structural skeleton. The converter
replaces its texture resources, frame list, animation keys and timeline length.
It does not inherit the donor's original frame count or frame rate.

GIF timing is resampled from the source frame durations on a 60-tick timeline.
The current safety limit is 120 output frames. If `duration * requested FPS`
exceeds 120, the full duration is retained and effective FPS is reduced.
