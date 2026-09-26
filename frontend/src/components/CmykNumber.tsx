/**
 * 数字を「CMYK の版ずれ」で刷ったように見せる表示（デザインシステムの .cmyk-num）。
 * 振り返りの読了冊数だけに使う。
 *
 * 仕組み: 同じ数字を4回重ねる。.paper が紙の白で抜いた土台、
 * .plate-c/m/y がシアン・マゼンタ・イエローの版。重なったところが黒くなる。
 * 読み上げには .paper の1つだけを渡し、残りは aria-hidden にする。
 */
export function CmykNumber({
  value,
  fontSize,
}: {
  value: number | string
  fontSize: number
}) {
  const text = String(value)
  return (
    <span className="cmyk-num" style={{ fontSize, fontWeight: 600 }}>
      <span className="paper">{text}</span>
      <span className="plate plate-c" aria-hidden="true">
        {text}
      </span>
      <span className="plate plate-m" aria-hidden="true">
        {text}
      </span>
      <span className="plate plate-y" aria-hidden="true">
        {text}
      </span>
    </span>
  )
}
