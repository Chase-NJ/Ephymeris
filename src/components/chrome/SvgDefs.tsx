/**
 * Document-level SVG defs, mounted once by the app shell.
 *
 * Holds the continuous-corner (squircle) clip path referenced by `.squircle`.
 * Declared in `objectBoundingBox` units so a single definition scales to
 * whatever size the mark is drawn at.
 */
export function SvgDefs() {
  return (
    <svg width="0" height="0" className="absolute" aria-hidden focusable="false">
      <defs>
        <clipPath id="ephymeris-squircle" clipPathUnits="objectBoundingBox">
          <path
            d="M0.5,0 C0.86,0 1,0.14 1,0.5 C1,0.86 0.86,1 0.5,1 C0.14,1 0,0.86 0,0.5 C0,0.14 0.14,0 0.5,0 Z"
          />
        </clipPath>
      </defs>
    </svg>
  );
}
