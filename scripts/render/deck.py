#!/usr/bin/env python3
# Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""Build a real, animated PowerPoint from framed screen renders.

  python3 deck.py spec.json out.pptx

spec.json:
{
  "bg": "#0E1726", "fg": "#FFFFFF", "accent": "#FF6600", "font": "Inter",
  "slides": [
    {"title": "Approve from your phone", "body": "One tap. Done.",
     "images": ["framed-light.png", "framed-dark.png"],
     "animate": "fly"}            # fly | fade | none (per image, in order)
  ]
}
Every slide gets a fade transition; each image enters on its own (fly up or
fade), one after the other, so the deck plays by itself when presented.
"""
import json, sys
from copy import deepcopy
from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Pt
from PIL import Image

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS = {"p": P}


def _rgb(h):
    return RGBColor.from_string(h.lstrip("#"))


def _transition(slide):
    xml = f'<p:transition xmlns:p="{P}" spd="med"><p:fade/></p:transition>'
    el = etree.fromstring(xml)
    sld = slide._element
    # transition must come right after clrMapOvr / cSld
    sld.insert(list(sld).index(sld.find("p:clrMapOvr", NS)) + 1 if sld.find("p:clrMapOvr", NS) is not None
               else list(sld).index(sld.find("p:cSld", NS)) + 1, el)


def _effect(spid, kind, idx, delay):
    first = "afterEffect" if idx == 0 else "withEffect"
    if kind == "fly":
        beh = f'''<p:set><p:cBhvr><p:cTn id="{{n}}" dur="1" fill="hold"/><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>
<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr><p:to><p:strVal val="visible"/></p:to></p:set>
<p:anim calcmode="lin" valueType="num"><p:cBhvr additive="base"><p:cTn id="{{n}}" dur="700" fill="hold"/><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>
<p:attrNameLst><p:attrName>ppt_y</p:attrName></p:attrNameLst></p:cBhvr><p:tavLst><p:tav tm="0"><p:val><p:strVal val="#ppt_y+0.25"/></p:val></p:tav>
<p:tav tm="100000"><p:val><p:strVal val="#ppt_y"/></p:val></p:tav></p:tavLst></p:anim>
<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{{n}}" dur="700"/><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cBhvr></p:animEffect>'''
        preset, cls = 2, "entr"
    else:
        beh = f'''<p:set><p:cBhvr><p:cTn id="{{n}}" dur="1" fill="hold"/><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>
<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr><p:to><p:strVal val="visible"/></p:to></p:set>
<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{{n}}" dur="600"/><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cBhvr></p:animEffect>'''
        preset, cls = 10, "entr"
    return (f'<p:par><p:cTn id="{{n}}" fill="hold"><p:stCondLst><p:cond delay="{delay}"/></p:stCondLst><p:childTnLst>'
            f'<p:par><p:cTn id="{{n}}" presetID="{preset}" presetClass="{cls}" presetSubtype="4" fill="hold" nodeType="{first}">'
            f'<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>{beh}</p:childTnLst></p:cTn></p:par>'
            f'</p:childTnLst></p:cTn></p:par>')


def _timing(slide, items):
    if not items:
        return
    pars, delay = "", 0
    for i, (spid, kind) in enumerate(items):
        pars += _effect(spid, kind, i, i * 450)  # each image 450 ms after the last
    body = (f'<p:timing xmlns:p="{P}"><p:tnLst><p:par><p:cTn id="{{n}}" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
            f'<p:seq concurrent="1" nextAc="seek"><p:cTn id="{{n}}" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
            f'<p:par><p:cTn id="{{n}}" fill="hold"><p:stCondLst><p:cond delay="indefinite"/><p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond></p:stCondLst><p:childTnLst>'
            f'{pars}</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn>'
            f'<p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
            f'<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>'
            f'</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>')
    n = iter(range(1, 999))
    while "{n}" in body:
        body = body.replace("{n}", str(next(n)), 1)
    el = etree.fromstring(body)
    slide._element.append(el)


def build(spec, out):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)  # 16:9
    W, H = prs.slide_width, prs.slide_height
    font = spec.get("font", "Inter")
    for s in spec["slides"]:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.background.fill.solid(); slide.background.fill.fore_color.rgb = _rgb(s.get("bg", spec.get("bg", "#0E1726")))
        fg = _rgb(s.get("fg", spec.get("fg", "#FFFFFF")))
        imgs = s.get("images", [])
        text_w = int(W * (0.42 if imgs else 0.84))
        if s.get("title"):
            tb = slide.shapes.add_textbox(int(W * 0.07), int(H * 0.30), text_w, int(H * 0.2)).text_frame
            tb.word_wrap = True
            r = tb.paragraphs[0].add_run(); r.text = s["title"]
            r.font.size, r.font.bold, r.font.name, r.font.color.rgb = Pt(40), True, font, fg
            bar = slide.shapes.add_shape(1, int(W * 0.07), int(H * 0.27), int(W * 0.05), Emu(60000))
            bar.fill.solid(); bar.fill.fore_color.rgb = _rgb(spec.get("accent", "#FF6600")); bar.line.fill.background()
        if s.get("body"):
            tb = slide.shapes.add_textbox(int(W * 0.07), int(H * 0.52), text_w, int(H * 0.3)).text_frame
            tb.word_wrap = True
            r = tb.paragraphs[0].add_run(); r.text = s["body"]
            r.font.size, r.font.name, r.font.color.rgb = Pt(20), font, fg
        anim, items = s.get("animate", "fly"), []
        if imgs:
            area_x = int(W * 0.50) if (s.get("title") or s.get("body")) else int(W * 0.05)
            area_w, area_h = W - area_x - int(W * 0.04), int(H * 0.92)
            gap = int(W * 0.01)
            sizes = [Image.open(p).size for p in imgs]
            h = area_h
            tot = sum(int(h * w0 / h0) for w0, h0 in sizes) + gap * (len(imgs) - 1)
            if tot > area_w:
                h = int(h * area_w / tot); tot = area_w
            x = area_x + (area_w - tot) // 2
            for p, (w0, h0) in zip(imgs, sizes):
                w = int(h * w0 / h0)
                pic = slide.shapes.add_picture(p, x, (H - h) // 2, w, h)
                x += w + gap
                if anim != "none":
                    items.append((pic.shape_id, anim))
        _transition(slide)
        _timing(slide, items)
    prs.save(out)
    print(out)


if __name__ == "__main__":
    build(json.load(open(sys.argv[1])), sys.argv[2])
