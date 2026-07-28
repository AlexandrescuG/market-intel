/**
 * SBF icon sprite — SPEC_icon_system.md.
 * One inline SVG sprite injected once, all symbols on a 24x24 grid,
 * stroke="currentColor" so icons inherit text color. Insert with:
 *   <span class="ic ic-24"><svg><use href="#ic-target"/></svg></span>
 * or, in a React chapter, window.SBFIcons.Icon({name:"target", size:24}).
 *
 * Scope: built to cover the emoji actually used in chapters 3 and 4
 * (SPEC_icon_system.md §0 count) — not the full course-wide rollout
 * (§6 steps 6-9 touch chapters outside this pass's scope, several of
 * them already closed for their own debug queues).
 */
(function () {
  var SYMBOLS = {
    // ── уже было в наборе как растр/иные форматы, здесь — тот же смысл в едином стиле ──
    "bar-chart": '<line x1="4" y1="21" x2="4" y2="13"/><line x1="10" y1="21" x2="10" y2="7"/><line x1="16" y1="21" x2="16" y2="11"/><line x1="21" y1="21" x2="3" y2="21"/>',
    "lightning": '<polygon points="13,2 4,14 11,14 9,22 20,9 13,9" fill="currentColor" stroke="none"/>',
    "check": '<polyline points="4,13 9,18 20,6"/>',
    "shield": '<path d="M12 3 L20 6 L20 12 C20 17 16.5 20 12 21 C7.5 20 4 17 4 12 L4 6 Z"/>',
    "target": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="0.8" fill="currentColor" stroke="none"/>',
    "trend-up": '<polyline points="3,17 10,10 14,14 21,6"/><polyline points="15,6 21,6 21,12"/>',
    "trend-down": '<polyline points="3,6 10,13 14,9 21,17"/><polyline points="21,10 21,17 14,17"/>',
    "warning": '<path d="M12 3 L22 20 L2 20 Z"/><line x1="12" y1="9.5" x2="12" y2="14.5"/><circle cx="12" cy="17" r="0.9" fill="currentColor" stroke="none"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><line x1="3" y1="12" x2="21" y2="12"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><line x1="12" y1="12" x2="12" y2="7"/><line x1="12" y1="12" x2="16" y2="14"/>',
    "house": '<path d="M4 11 L12 4 L20 11 L20 20 L4 20 Z"/><line x1="9" y1="20" x2="9" y2="14" style="display:none"/>',
    "briefcase": '<rect x="3" y="8" width="18" height="12" rx="1.5"/><path d="M8 8 V6 a2 2 0 0 1 2 -2 h4 a2 2 0 0 1 2 2 V8"/><line x1="3" y1="13" x2="21" y2="13"/>',
    "money": '<rect x="2" y="6" width="20" height="12" rx="1.5"/><circle cx="12" cy="12" r="3.2"/>',
    "shopping": '<path d="M6 8 L4 21 H20 L18 8 Z"/><path d="M8 8 V6 a4 4 0 0 1 8 0 V8"/>',
    // ── новые, дорисованы для §3.2 ──
    "bank": '<path d="M3 10 L12 4 L21 10 Z"/><line x1="4" y1="10" x2="4" y2="19"/><line x1="8" y1="10" x2="8" y2="19"/><line x1="12" y1="10" x2="12" y2="19"/><line x1="16" y1="10" x2="16" y2="19"/><line x1="20" y1="10" x2="20" y2="19"/><line x1="2" y1="19" x2="22" y2="19"/><line x1="2" y1="21.5" x2="22" y2="21.5"/>',
    "factory": '<path d="M3 21 V11 L9 14 V11 L15 14 V8 L21 11 V21 Z"/>',
    "oil-barrel": '<rect x="6" y="3" width="12" height="18" rx="2"/><line x1="6" y1="8" x2="18" y2="8"/><line x1="6" y1="16" x2="18" y2="16"/>',
    "bitcoin": '<circle cx="12" cy="12" r="9"/><path d="M9.5 8 H13.5 a2 2 0 0 1 0 4 H9.5 M9.5 12 H14 a2 2 0 0 1 0 4 H9.5 M9.5 8 V16 M11 6 V8 M11 16 V18 M13.5 6 V8 M13.5 16 V18"/>',
    "banknote": '<rect x="2" y="6" width="20" height="12" rx="1.5"/><circle cx="12" cy="12" r="2.6"/><line x1="5" y1="9" x2="5" y2="9.01"/><line x1="19" y1="15" x2="19" y2="15.01"/>',
    "mask": '<path d="M4 9 C4 6 7 4 12 4 C17 4 20 6 20 9 C20 15 17 20 12 20 C7 20 4 15 4 9 Z"/><path d="M7 9 C7.5 8 9 8 9.5 9" /><path d="M14.5 9 C15 8 16.5 8 17 9"/><path d="M9 14 C10 15.5 14 15.5 15 14"/>',
    "box": '<path d="M3 8 L12 4 L21 8 L12 12 Z"/><path d="M3 8 V16 L12 20 V12"/><path d="M21 8 V16 L12 20"/>',
    "magnifier": '<circle cx="10.5" cy="10.5" r="6.5"/><line x1="15.5" y1="15.5" x2="21" y2="21"/>',
    "chart-candles": '<line x1="6" y1="4" x2="6" y2="20"/><rect x="4" y="9" width="4" height="6"/><line x1="14" y1="2" x2="14" y2="18"/><rect x="12" y="6" width="4" height="8"/><line x1="20" y1="6" x2="20" y2="20"/><rect x="18" y="10" width="4" height="5"/>',
    "swap": '<polyline points="17,3 21,7 17,11"/><line x1="21" y1="7" x2="3" y2="7"/><polyline points="7,13 3,17 7,21"/><line x1="3" y1="17" x2="21" y2="17"/>',
    "scales": '<line x1="12" y1="3" x2="12" y2="21"/><line x1="5" y1="7" x2="19" y2="7"/><path d="M2 15 L5 7 L8 15 a3.2 3.2 0 0 1 -6 0Z"/><path d="M16 15 L19 7 L22 15 a3.2 3.2 0 0 1 -6 0Z"/><line x1="9" y1="21" x2="15" y2="21"/>',
    "hourglass": '<path d="M6 3 H18 V7 L13 12 L18 17 V21 H6 V17 L11 12 L6 7 Z"/><line x1="6" y1="3" x2="18" y2="3"/><line x1="6" y1="21" x2="18" y2="21"/>',
    "close": '<line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/>',
    "bomb": '<circle cx="11" cy="14" r="7"/><path d="M15 8 L18 5"/><path d="M17 3 L20 6"/><circle cx="19" cy="4" r="1" fill="currentColor" stroke="none"/>',
    "book": '<path d="M4 5 C4 5 8 4 12 6 C16 4 20 5 20 5 L20 18 C20 18 16 17 12 19 C8 17 4 18 4 18 Z"/><line x1="12" y1="6" x2="12" y2="19"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4 6.5 6.5 0 0 0 20 14.5Z"/>',
    "droplet": '<path d="M12 3 C12 3 5 12 5 16.5 A7 7 0 0 0 19 16.5 C19 12 12 3 12 3 Z"/>',
    "person": '<circle cx="12" cy="8" r="4"/><path d="M4 21 C4 16 7.5 14 12 14 C16.5 14 20 16 20 21"/>',
    "building": '<rect x="5" y="3" width="14" height="18"/><line x1="9" y1="7" x2="9" y2="9"/><line x1="15" y1="7" x2="15" y2="9"/><line x1="9" y1="12" x2="9" y2="14"/><line x1="15" y1="12" x2="15" y2="14"/><line x1="10" y1="21" x2="10" y2="17"/><line x1="14" y1="21" x2="14" y2="17"/>',
    "pin": '<path d="M12 21 C12 21 5 13.5 5 9 A7 7 0 0 1 19 9 C19 13.5 12 21 12 21 Z"/><circle cx="12" cy="9" r="2.3"/>',
    "traffic-light": '<rect x="8" y="2" width="8" height="18" rx="3"/><circle cx="12" cy="6.5" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="11" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="15.5" r="1.5" fill="currentColor" stroke="none"/><line x1="12" y1="20" x2="12" y2="22"/>',
    "shuffle": '<polyline points="16,3 21,3 21,8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21,16 21,21 16,21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/>',
    "game": '<rect x="2" y="8" width="20" height="10" rx="5"/><line x1="7" y1="11" x2="7" y2="15"/><line x1="5" y1="13" x2="9" y2="13"/><circle cx="16" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="18" cy="14" r="1" fill="currentColor" stroke="none"/>',
  };

  function injectSprite() {
    if (document.getElementById("sbf-icon-sprite")) return;
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.id = "sbf-icon-sprite";
    svg.setAttribute("style", "position:absolute;width:0;height:0;overflow:hidden");
    svg.setAttribute("aria-hidden", "true");
    var html = "";
    Object.keys(SYMBOLS).forEach(function (name) {
      html += '<symbol id="ic-' + name + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + SYMBOLS[name] + "</symbol>";
    });
    svg.innerHTML = html;
    document.body.appendChild(svg);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectSprite);
  } else {
    injectSprite();
  }

  // Vanilla-JS helper: window.SBFIcons.html("target", {size:24, className:"..."})
  function iconHtml(name, opts) {
    opts = opts || {};
    var size = opts.size || 24;
    var cls = "ic" + (opts.className ? " " + opts.className : "");
    var style = "width:" + size + "px;height:" + size + "px;display:inline-block;vertical-align:-0.125em" + (opts.color ? ";color:" + opts.color : "");
    return '<svg class="' + cls + '" style="' + style + '" aria-hidden="true"><use href="#ic-' + name + '"></use></svg>';
  }

  window.SBFIcons = {
    names: Object.keys(SYMBOLS),
    html: iconHtml,
    // React component for chapter books: <Icon name="target" size={24}/>
    Icon: function (props) {
      var size = props.size || 24;
      var style = Object.assign({ width: size, height: size, display: "inline-block", verticalAlign: "-0.125em", flexShrink: 0 }, props.color ? { color: props.color } : {}, props.style || {});
      return React.createElement("svg", { style: style, "aria-hidden": "true", className: props.className },
        React.createElement("use", { href: "#ic-" + props.name }));
    },
  };
})();
