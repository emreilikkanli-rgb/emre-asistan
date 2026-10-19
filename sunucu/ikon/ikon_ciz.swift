// EA logosunu PNG olarak çizer (uygulamadaki logoyla aynı: renk geçişli çerçeve, koyu iç zemin, parlayan "EA").
// Kullanım: swift ikon_ciz.swift <çıktı.png> <ios|mac>
//   ios: tam kare (telefon kendi köşelerini yuvarlar)   mac: macOS simge ızgarası (kenar boşluklu, gölgeli)
import AppKit

let args = CommandLine.arguments
let out = args.count > 1 ? args[1] : "ea.png"
let mac = args.count > 2 && args[2] == "mac"
let S: CGFloat = 1024

func renk(_ h: UInt32, _ a: CGFloat = 1) -> CGColor {
    CGColor(red: CGFloat((h >> 16) & 255) / 255, green: CGFloat((h >> 8) & 255) / 255, blue: CGFloat(h & 255) / 255, alpha: a)
}
func karisim(_ a: [CGFloat], _ b: [CGFloat], _ t: CGFloat) -> [CGFloat] { zip(a, b).map { $0 + ($1 - $0) * t } }
func rgb(_ h: UInt32) -> [CGFloat] { [CGFloat((h >> 16) & 255) / 255, CGFloat((h >> 8) & 255) / 255, CGFloat(h & 255) / 255] }

let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(S), pixelsHigh: Int(S), bitsPerSample: 8, samplesPerPixel: 4,
                           hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
let ctx = NSGraphicsContext(bitmapImageRep: rep)!.cgContext
ctx.setAllowsAntialiasing(true); ctx.interpolationQuality = .high

// Dış şekil: iOS için tam kare, Mac için 824 px'lik yuvarlatılmış kare (Big Sur ızgarası)
let dis: CGRect = mac ? CGRect(x: 100, y: 100, width: 824, height: 824) : CGRect(x: 0, y: 0, width: S, height: S)
let disR: CGFloat = mac ? 185 : 0
let disYol = CGPath(roundedRect: dis, cornerWidth: disR, cornerHeight: disR, transform: nil)

if mac {  // yumuşak gölge
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -14), blur: 34, color: renk(0x000000, 0.45))
    ctx.addPath(disYol); ctx.setFillColor(renk(0x0f0d22)); ctx.fillPath()
    ctx.restoreGState()
}

// 1) Renk geçişli çerçeve: mor → eflatun → mercan → mor (dairesel)
ctx.saveGState()
ctx.addPath(disYol); ctx.clip()
let duraklar: [UInt32] = [0x7c6cff, 0xc06cff, 0xff8f6c, 0x7c6cff]
let merkez = CGPoint(x: dis.midX, y: dis.midY)
let dilim = 720
for i in 0..<dilim {
    let t = CGFloat(i) / CGFloat(dilim)
    let k = t * CGFloat(duraklar.count - 1)
    let j = min(Int(k), duraklar.count - 2)
    let c = karisim(rgb(duraklar[j]), rgb(duraklar[j + 1]), k - CGFloat(j))
    let a0 = (210.0 / 180.0 * .pi) + t * 2 * .pi - .pi / 2, a1 = a0 + 2 * .pi / CGFloat(dilim) + 0.004
    ctx.move(to: merkez)
    ctx.addArc(center: merkez, radius: S, startAngle: -a0, endAngle: -a1, clockwise: true)
    ctx.closePath()
    ctx.setFillColor(CGColor(red: c[0], green: c[1], blue: c[2], alpha: 1)); ctx.fillPath()
}
ctx.restoreGState()

// 2) Koyu iç zemin (ince renkli çerçeve kalacak şekilde)
let kalinlik = dis.width * (mac ? 0.045 : 0.05)
let ic = dis.insetBy(dx: kalinlik, dy: kalinlik)
let icR = mac ? disR - kalinlik : dis.width * 0.12
let icYol = CGPath(roundedRect: ic, cornerWidth: icR, cornerHeight: icR, transform: nil)
ctx.saveGState()
ctx.addPath(icYol); ctx.clip()
let zemin = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: [renk(0x1f1b42), renk(0x0f0d22)] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(zemin, start: CGPoint(x: ic.minX, y: ic.maxY), end: CGPoint(x: ic.maxX, y: ic.minY), options: [])
// iç ışıltı: sol üstte mor, sağ altta mercan hale
for (nokta, r, c, a) in [(CGPoint(x: ic.minX + ic.width * 0.25, y: ic.maxY - ic.height * 0.2), ic.width * 0.75, 0x7c6cff as UInt32, 0.38 as CGFloat),
                          (CGPoint(x: ic.maxX - ic.width * 0.15, y: ic.minY + ic.height * 0.1), ic.width * 0.6, 0xff8f6c as UInt32, 0.22 as CGFloat)] {
    let g = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: [renk(c, a), renk(c, 0)] as CFArray, locations: [0, 1])!
    ctx.drawRadialGradient(g, startCenter: nokta, startRadius: 0, endCenter: nokta, endRadius: r, options: [])
}
ctx.restoreGState()

// 3) "EA" yazısı: beyazdan leylak ve şeftaliye geçişli
let yaziBoy = ic.width * 0.40
let font = NSFont.systemFont(ofSize: yaziBoy, weight: .heavy)
let yazi = NSAttributedString(string: "EA", attributes: [.font: font, .foregroundColor: NSColor.white, .kern: -yaziBoy * 0.02])
let line = CTLineCreateWithAttributedString(yazi)
let sinir = CTLineGetImageBounds(line, ctx)
let konum = CGPoint(x: ic.midX - sinir.width / 2 - sinir.minX, y: ic.midY - sinir.height / 2 - sinir.minY)
// yazı maskesi
let maske = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(S), pixelsHigh: Int(S), bitsPerSample: 8, samplesPerPixel: 4,
                             hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
let mctx = NSGraphicsContext(bitmapImageRep: maske)!.cgContext
mctx.textPosition = konum
CTLineDraw(line, mctx)
let maskeImg = mctx.makeImage()!
// hafif parıltı
ctx.saveGState()
ctx.setShadow(offset: .zero, blur: 40, color: renk(0xb9a8ff, 0.55))
ctx.textPosition = konum
ctx.setFillColor(renk(0xffffff, 0.9))
CTLineDraw(line, ctx)
ctx.restoreGState()
ctx.saveGState()
ctx.clip(to: CGRect(x: 0, y: 0, width: S, height: S), mask: maskeImg)
let yaziGrad = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: [renk(0xffffff), renk(0xd9d2ff), renk(0xffc9b8)] as CFArray, locations: [0, 0.6, 1])!
ctx.drawLinearGradient(yaziGrad, start: CGPoint(x: ic.minX + ic.width * 0.2, y: ic.maxY - ic.height * 0.25), end: CGPoint(x: ic.maxX - ic.width * 0.2, y: ic.minY + ic.height * 0.25), options: [])
ctx.restoreGState()

// 4) Sağ üstte küçük yıldız parıltısı (✦)
func yildiz(_ c: CGPoint, _ r: CGFloat) {
    let p = CGMutablePath()
    for i in 0..<8 {
        let a = CGFloat(i) * .pi / 4 + .pi / 2
        let rr = i % 2 == 0 ? r : r * 0.22
        let n = CGPoint(x: c.x + cos(a) * rr, y: c.y + sin(a) * rr)
        if i == 0 { p.move(to: n) } else { p.addLine(to: n) }
    }
    p.closeSubpath()
    ctx.saveGState()
    ctx.setShadow(offset: .zero, blur: r * 0.9, color: renk(0xffffff, 0.8))
    ctx.addPath(p); ctx.setFillColor(renk(0xffffff)); ctx.fillPath()
    ctx.restoreGState()
}
yildiz(CGPoint(x: ic.maxX - ic.width * 0.17, y: ic.maxY - ic.height * 0.17), ic.width * 0.075)
yildiz(CGPoint(x: ic.maxX - ic.width * 0.29, y: ic.maxY - ic.height * 0.09), ic.width * 0.03)

// 5) Üst parlaklık (cam etkisi)
ctx.saveGState()
ctx.addPath(disYol); ctx.clip()
let parlak = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: [renk(0xffffff, 0.16), renk(0xffffff, 0)] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(parlak, start: CGPoint(x: dis.minX, y: dis.maxY), end: CGPoint(x: dis.midX, y: dis.midY), options: [])
ctx.restoreGState()

let png = rep.representation(using: .png, properties: [:])!
try! png.write(to: URL(fileURLWithPath: out))
print("yazıldı:", out)
