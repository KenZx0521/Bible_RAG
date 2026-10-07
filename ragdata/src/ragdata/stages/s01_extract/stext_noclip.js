// S1: unclipped per-glyph extraction of one PDF (design §4, audit §2.3).
// Usage: mutool run stext_noclip.js <pdf>   -> JSON lines on stdout, in page order:
//   {"k":"page","p":N,"bounds":[x0,y0,x1,y1]}
//   {"k":"line","p":N,"chars":[[c,x0,x1,y,font,size,color],...]}   one per structured-text line
//   {"k":"stroke","p":N,"lw":w,"path":[["m",x,y],["l",x,y],["c",x1,y1,x2,y2,x3,y3],["z"]]}
// mediabox-clip=no keeps the glyphs typeset past the right page edge (852 in the corpus);
// the default clip drops them. Coordinates are page space (y down), rounded to 0.01 pt.
var doc = Document.openDocument(scriptArgs[0]);
function r2(v) { return Math.round(v * 100) / 100; }
function hex(c) { var h = (c >>> 0).toString(16); while (h.length < 6) h = "0" + h; return "#" + h.slice(-6); }
function emit(obj) { print(JSON.stringify(obj)); }
function lines(page, p) {
  var st = page.toStructuredText("mediabox-clip=no,preserve-whitespace");
  var line = null;
  st.walk({
    beginLine: function () { line = []; },
    onChar: function (c, origin, font, size, quad, color) {
      line.push([c, r2(origin[0]), r2(quad[2]), r2(origin[1]), font.getName().split("+").pop(),
                 r2(size), hex(color)]);
    },
    endLine: function () { if (line && line.length) emit({k: "line", p: p, chars: line}); line = null; }
  });
}
function strokes(page, p) {
  var device = {
    strokePath: function (path, stroke, ctm) {
      var ops = [];
      function pt(x, y) { return [r2(ctm[0] * x + ctm[2] * y + ctm[4]), r2(ctm[1] * x + ctm[3] * y + ctm[5])]; }
      path.walk({
        moveTo: function (x, y) { ops.push(["m"].concat(pt(x, y))); },
        lineTo: function (x, y) { ops.push(["l"].concat(pt(x, y))); },
        curveTo: function (x1, y1, x2, y2, x3, y3) { ops.push(["c"].concat(pt(x1, y1), pt(x2, y2), pt(x3, y3))); },
        closePath: function () { ops.push(["z"]); }
      });
      emit({k: "stroke", p: p, lw: Math.round(stroke.lineWidth * 10000) / 10000, path: ops});
    }
  };
  page.toDisplayList().run(device, Matrix.identity);
}
var n = doc.countPages();
for (var i = 0; i < n; i++) {
  var page = doc.loadPage(i);
  var b = page.getBounds();
  emit({k: "page", p: i + 1, bounds: [r2(b[0]), r2(b[1]), r2(b[2]), r2(b[3])]});
  lines(page, i + 1);
  strokes(page, i + 1);
}
