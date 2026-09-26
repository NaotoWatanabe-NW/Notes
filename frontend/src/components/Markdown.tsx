import type { ReactNode } from 'react'
import { Children, isValidElement } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// 「p.96」のような出典。斜体の引用の中でも、ここだけは正体で小さく出す
const PAGE_REF = /(p\.\d+)/g

/** 文字列の中の「p.96」を小さな添え字に置き換える */
function markPageRefs(node: ReactNode): ReactNode {
  if (typeof node === 'string') {
    const parts = node.split(PAGE_REF)
    if (parts.length === 1) return node
    return parts.map((part, index) =>
      PAGE_REF.test(part) ? (
        <span key={index} className="page-ref">
          {part}
        </span>
      ) : (
        part
      ),
    )
  }
  if (Array.isArray(node)) return Children.map(node, markPageRefs)
  // 要素の中身はそれぞれのコンポーネントが処理するので、ここでは触らない
  if (isValidElement(node)) return node
  return node
}

/**
 * レポート本文の Markdown を、デザインの対応表どおりに表示する。
 * react-markdown は既定で生のHTMLを描画しないので、書いた内容がそのまま
 * スクリプトとして動いてしまうことはない。
 */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children: inner }) => <p>{markPageRefs(inner)}</p>,
          li: ({ children: inner }) => <li>{markPageRefs(inner)}</li>,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
