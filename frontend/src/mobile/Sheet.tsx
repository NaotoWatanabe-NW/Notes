import type { ReactNode } from 'react'

type Props = {
  /** half: 画面の52% / tall: 88% / full: 上54pxを残して全面 */
  size?: 'half' | 'tall' | 'full'
  /** 背後をどれだけ暗くするか */
  dim?: 'soft' | 'strong'
  onClose: () => void
  /** グラバーを押したときの動き（高さの切り替えなど） */
  onGrab?: () => void
  children: ReactNode
}

/**
 * 下から出るシート。メモの記録・執筆中の道具・次に読む本で使う。
 * 背後をタップすると閉じる。
 */
export function Sheet({ size = 'half', dim = 'soft', onClose, onGrab, children }: Props) {
  return (
    <div
      className="m-sheet-backdrop"
      data-dim={dim === 'strong' ? 'strong' : undefined}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className={`m-sheet m-sheet-${size}`} role="dialog">
        <button
          type="button"
          className="m-grabber"
          aria-label={onGrab ? '高さを切り替える' : '閉じる'}
          onClick={onGrab ?? onClose}
        />
        {children}
      </div>
    </div>
  )
}
