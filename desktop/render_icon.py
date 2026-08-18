"""Render the Mira orb+monogram logo to desktop PNG icons and a Windows .ico.

Draws the same design as web/public/favicon.svg with PIL/numpy (the embeddable
runtime ships Pillow + numpy, and cairosvg needs libcairo which isn't bundled):
dark rounded tile, violet radial glow, and a rounded-stroke "M" monogram.
"""

import numpy as np
from PIL import Image, ImageDraw

S = 512  # master size; downscale for the small assets


def rounded_rect_mask(size, radius, pad=0):
    """RGBA mask with a rounded-rectangle opaque area."""
    img = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([pad, pad, size - 1 - pad, size - 1 - pad], radius=radius, fill=255)
    return img


def radial(size, cx, cy, stops, r_norm=0.5, power=1.0):
    """Radial RGBA layer. stops = [(offset, (r,g,b,a)), ...] blended outward."""
    y, x = np.mgrid[0:size, 0:size]
    d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / (r_norm * size)
    d = np.clip(d, 0.0, 1.0) ** power
    channels = np.zeros((size, size, 4), dtype=np.float32)
    for i in range(4):
        channels[:, :, i] = np.interp(d, [s[0] for s in stops], [s[1][i] for s in stops])
    return Image.fromarray(np.clip(channels, 0, 255).astype(np.uint8), "RGBA")


def compose(layers):
    base = None
    for img in layers:
        if base is None:
            base = img.convert("RGBA")
        else:
            base = Image.alpha_composite(base, img.convert("RGBA"))
    return base


def render_icon(mode):
    """mode in {"idle","typing","alert"}. Returns an RGBA image at S."""
    if mode == "alert":
        bg = [(0.0, (42, 31, 16, 255)), (1.0, (11, 11, 18, 255))]
        halo = [(0.0, (255, 179, 107, 242)), (0.45, (255, 154, 61, 102)), (1.0, (255, 154, 61, 0))]
        breath = [(0.0, (255, 201, 138, 140)), (0.7, (255, 154, 61, 36)), (1.0, (255, 154, 61, 0))]
        m = [(0.0, (255, 243, 224, 255)), (1.0, (255, 178, 94, 255))]
    else:
        bg = [(0.0, (23, 19, 41, 255)), (1.0, (11, 11, 18, 255))]
        halo = [(0.0, (143, 107, 255, 217)), (0.45, (124, 92, 255, 71)), (1.0, (124, 92, 255, 0))]
        breath = [(0.0, (185, 167, 255, 128)), (0.7, (124, 92, 255, 31)), (1.0, (124, 92, 255, 0))]
        m = [(0.0, (242, 236, 255, 255)), (1.0, (177, 133, 255, 255))]

    tile = radial(S, S / 2, S / 2, bg, r_norm=0.7071, power=1.0)
    rmask = rounded_rect_mask(S, int(S * 0.22)).point(lambda a: a // 1)

    glow = compose([radial(S, S / 2, S / 2, breath, r_norm=0.5, power=1.0),
                    radial(S, S / 2, S / 2, halo, r_norm=0.4, power=1.0)])

    m_img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    md = ImageDraw.Draw(m_img)
    lw = int(S * 0.11)
    y_top, y_bot = S * 0.33, S * 0.67
    x_l, x_r = S * 0.33, S * 0.67
    # rounded-stroke M via thick lines + joint caps
    md.line([(x_l, y_bot), (x_l, y_top)], fill=m[1][1], width=lw)
    md.line([(x_r, y_bot), (x_r, y_top)], fill=m[1][1], width=lw)
    md.line([(x_l, y_top), (S / 2, y_bot)], fill=m[1][1], width=lw)
    md.line([(S / 2, y_bot), (x_r, y_top)], fill=m[1][1], width=lw)
    # round the four corners with filled circles
    for p in [(x_l, y_top), (x_r, y_top), (x_l, y_bot), (x_r, y_bot)]:
        md.ellipse([p[0] - lw / 2, p[1] - lw / 2, p[0] + lw / 2, p[1] + lw / 2], fill=m[1][1])

    # vertical gradient on the M: mask top→bottom
    grad = Image.new("L", (S, S), 0)
    gd = ImageDraw.Draw(grad)
    gd.rectangle([0, 0, S, S], fill=0)
    y, x = np.mgrid[0:S, 0:S]
    t = np.clip(y / S, 0, 1)
    m_grad = np.interp(t, [0, 1], [m[0][1][3], m[1][1][3]]).astype(np.uint8)
    m_img.putalpha(Image.composite(Image.fromarray(m_grad, "L"), Image.new("L", (S, S), 0),
                                   m_img.split()[3] if m_img.getbbox() else Image.new("L", (S, S), 0)))

    # simplify: keep M opaque where drawn, tint by vertical gradient
    alpha = m_img.split()[3]
    colored = Image.merge("RGBA", (
        Image.fromarray(np.interp(t, [0, 1], [m[0][1][0], m[1][1][0]]).astype(np.uint8), "L"),
        Image.fromarray(np.interp(t, [0, 1], [m[0][1][1], m[1][1][1]]).astype(np.uint8), "L"),
        Image.fromarray(np.interp(t, [0, 1], [m[0][1][2], m[1][1][2]]).astype(np.uint8), "L"),
        alpha,
    ))
    m_img = colored

    result = compose([tile, glow, m_img])
    # apply rounded tile mask so corners are transparent
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(result, (0, 0), rmask)
    return out


def main():
    import os
    assets = os.path.join(os.path.dirname(__file__), "assets")
    os.makedirs(assets, exist_ok=True)

    idle = render_icon("idle").resize((64, 64), Image.LANCZOS)
    idle.save(os.path.join(assets, "orb.png"))
    idle.save(os.path.join(assets, "tray.png"))

    # Windows .ico: 256 + 64 + 48 + 32 + 16
    master = render_icon("idle").resize((256, 256), Image.LANCZOS)
    sizes = [(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)]
    ico_path = os.path.join(assets, "icon.ico")
    master.save(ico_path, format="ICO", sizes=sizes)
    print("wrote", ico_path)


if __name__ == "__main__":
    main()