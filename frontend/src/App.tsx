import { useEffect, useState } from 'react'
import { DesktopShell } from './DesktopShell'
import { MobileApp } from './mobile/MobileApp'
import { useAppData } from './useAppData'

/**
 * デザインは PC（3ペイン）とスマホ（タブバー＋単一画面）で別物なので、
 * 幅でどちらの画面を出すかを切り替える。中身を共有して無理に伸び縮みさせると、
 * どちらの設計にも合わないものになる。
 */
const MOBILE_MAX = 820

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(
    () => window.matchMedia(`(max-width: ${MOBILE_MAX}px)`).matches,
  )
  useEffect(() => {
    const media = window.matchMedia(`(max-width: ${MOBILE_MAX}px)`)
    const update = () => setIsMobile(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  return isMobile
}

export default function App() {
  // データの読み書きは PC版・モバイル版で同じものを使う
  const data = useAppData()
  return useIsMobile() ? <MobileApp data={data} /> : <DesktopShell data={data} />
}
