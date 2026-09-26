/**
 * セグメント選択（積読 / 読書中 / 読了 など）。
 * デザインシステムの .seg / .seg-opt は「中のラジオが checked か」で見た目が
 * 変わる作りなので、本物の radio を隠して置いている。
 */
type Props<T extends string> = {
  name: string
  value: T
  options: { value: T; label: string }[]
  onChange: (next: T) => void
}

export function Segmented<T extends string>({
  name,
  value,
  options,
  onChange,
}: Props<T>) {
  return (
    <div className="seg" role="group">
      {options.map((option) => (
        <label key={option.value} className="seg-opt">
          <input
            type="radio"
            name={name}
            checked={option.value === value}
            onChange={() => onChange(option.value)}
          />
          {option.label}
        </label>
      ))}
    </div>
  )
}
