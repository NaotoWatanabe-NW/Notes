import { useEffect } from 'react'

type Props = {
  message: string
  onDone: () => void
}

/** 右下に出て 2.4 秒で消える通知 */
export function Toast({ message, onDone }: Props) {
  useEffect(() => {
    const timer = window.setTimeout(onDone, 2400)
    return () => window.clearTimeout(timer)
  }, [message, onDone])

  return (
    <div className="toast" role="status">
      <i className="ph-duotone ph-check-circle" />
      {message}
    </div>
  )
}
