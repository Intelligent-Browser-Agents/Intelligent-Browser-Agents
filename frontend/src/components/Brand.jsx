import mark from "../assets/brand/humani-mark.svg";

/**
 * The HUMANi lockup: mark plus wordmark. The wordmark is set in text (dark
 * navy HUMAN, brand-blue i) so it stays crisp at any size and inherits the
 * app font.
 */
export default function Brand({ size = 28, wordmark = true, className = "" }) {
  return (
    <span className={`brand ${className}`.trim()}>
      <img src={mark} alt="" width={size} height={size} draggable={false} />
      {wordmark && (
        <span className="brand-wordmark" style={{ fontSize: size * 0.62 }}>
          HUMAN<span className="brand-wordmark-i">i</span>
        </span>
      )}
    </span>
  );
}
