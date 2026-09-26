import { useState } from 'react'
import type { BookInfo, BookStatus } from '../api'
import { lookupIsbn } from '../api'
import { Toast } from '../components/Toast'
import type { NoteFilter } from '../types'
import type { AppData } from '../useAppData'
import { BookScreen } from './BookScreen'
import { LibraryScreen } from './LibraryScreen'
import { NextBookSheet } from './NextBookSheet'
import { NoteDetailScreen } from './NoteDetailScreen'
import { NotesScreen } from './NotesScreen'
import { ReportScreen } from './ReportScreen'
import { ReviewScreen } from './ReviewScreen'
import { SearchScreen } from './SearchScreen'
import { SettingsScreen } from './SettingsScreen'
import type { MobileTab } from './TabBar'
import { TabBar } from './TabBar'

/**
 * モバイル版（デザイン #7a〜7g）。
 *
 * タブバー＋単一画面。本の詳細と設定はタブの上に重ね（タブバーは残す）、
 * レポート執筆と「次に読む本」は全面に出す（タブバーは隠す）。
 */
export function MobileApp({ data }: { data: AppData }) {
  const {
    books,
    notes,
    settings,
    toast,
    setToast,
    setSelectedBookId,
    bookDetail,
    bookNotes,
    justFinished,
    clearJustFinished,
    reload,
    notify,
    fail,
    updateBook,
    addBook,
    addNote,
    removeNote,
    removeBook,
    changeSettings,
  } = data

  const [tab, setTab] = useState<MobileTab>('library')
  const [libraryFilter, setLibraryFilter] = useState<BookStatus | 'all'>('all')
  const [noteFilter, setNoteFilter] = useState<NoteFilter>(null)
  const [selectedNoteId, setSelectedNoteId] = useState<number | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [writingBookId, setWritingBookId] = useState<number | null>(null)

  const selectedNote = notes.find((note) => note.id === selectedNoteId) ?? null
  const writingBook =
    writingBookId !== null && bookDetail?.id === writingBookId ? bookDetail : null

  /** 本棚でその本を開く。絞り込みで隠れるなら「すべて」に戻す */
  function openBook(id: number) {
    const book = books.find((item) => item.id === id)
    if (book && libraryFilter !== 'all' && book.status !== libraryFilter) {
      setLibraryFilter('all')
    }
    setTab('library')
    setShowSettings(false)
    setSelectedBookId(id)
  }

  async function addFromCatalog(info: BookInfo) {
    try {
      // ISBN しか分からない候補は、ここで書誌を引いてから足す
      const full = info.title ? info : await lookupIsbn(info.isbn)
      const created = await addBook({
        isbn: full.isbn,
        title: full.title,
        author: full.author,
        publisher: full.publisher,
        category: full.category,
        cover_url: full.cover_url,
        total: full.total,
        status: 'unread',
      })
      setLibraryFilter('all')
      notify(`「${created.title}」を積読に追加しました`)
    } catch (error) {
      fail(error, '本を追加できませんでした')
    }
  }

  function renderScreen() {
    if (showSettings && settings) {
      return (
        <SettingsScreen
          settings={settings}
          books={books}
          notes={notes}
          onChange={changeSettings}
          onBack={() => setShowSettings(false)}
        />
      )
    }

    if (tab === 'library') {
      if (bookDetail) {
        return (
          <BookScreen
            book={bookDetail}
            notes={bookNotes}
            onBack={() => setSelectedBookId(null)}
            onUpdate={(payload) => updateBook(bookDetail.id, payload)}
            onAddNote={(payload) => addNote(bookDetail.id, payload)}
            onDeleteNote={removeNote}
            onWriteReport={() => setWritingBookId(bookDetail.id)}
            onDelete={() => removeBook(bookDetail)}
            onReload={() => void reload()}
            onError={setToast}
          />
        )
      }
      return (
        <LibraryScreen
          books={books}
          filter={libraryFilter}
          onFilter={setLibraryFilter}
          onSelect={setSelectedBookId}
          onSearch={() => setTab('search')}
          onSettings={() => setShowSettings(true)}
        />
      )
    }

    if (tab === 'notes') {
      if (selectedNote) {
        return (
          <NoteDetailScreen
            note={selectedNote}
            siblings={notes}
            onSelectNote={setSelectedNoteId}
            onOpenBook={openBook}
            onBack={() => setSelectedNoteId(null)}
          />
        )
      }
      return (
        <NotesScreen
          notes={notes}
          filter={noteFilter}
          onFilter={setNoteFilter}
          onSelect={setSelectedNoteId}
        />
      )
    }

    if (tab === 'review') {
      return <ReviewScreen version={books.length + notes.length} onOpenBook={openBook} />
    }

    return (
      <SearchScreen
        books={books}
        notes={notes}
        onOpenBook={openBook}
        onOpenNote={(id) => {
          const note = notes.find((item) => item.id === id)
          if (note && noteFilter !== null && note.kind !== noteFilter) setNoteFilter(null)
          setTab('notes')
          setSelectedNoteId(id)
        }}
        onAdd={addFromCatalog}
        onClose={() => setTab('library')}
      />
    )
  }

  return (
    <div className="m-app">
      {renderScreen()}
      <TabBar
        tab={tab}
        onChange={(next) => {
          setShowSettings(false)
          // 同じタブをもう一度押したら、詳細から一覧へ戻る
          if (next === tab) {
            if (next === 'library') setSelectedBookId(null)
            if (next === 'notes') setSelectedNoteId(null)
          }
          setTab(next)
        }}
      />

      {writingBook ? (
        <ReportScreen
          book={writingBook}
          notes={bookNotes}
          onSave={(markdown) => {
            void updateBook(writingBook.id, { report_md: markdown })
          }}
          onClose={async (markdown) => {
            await updateBook(writingBook.id, { report_md: markdown })
            setWritingBookId(null)
            notify('レポートを保存しました')
          }}
          onUpdateBook={(payload) => updateBook(writingBook.id, payload)}
        />
      ) : null}

      {justFinished !== null ? (
        <NextBookSheet
          bookId={justFinished}
          rating={books.find((book) => book.id === justFinished)?.rating ?? null}
          onRate={(rating) => updateBook(justFinished, { rating })}
          onAdded={() => {
            void reload()
            setLibraryFilter('all')
          }}
          onWriteReport={() => {
            setWritingBookId(justFinished)
            clearJustFinished()
          }}
          onClose={clearJustFinished}
          onError={setToast}
        />
      ) : null}

      {toast ? <Toast message={toast} onDone={() => setToast(null)} /> : null}
    </div>
  )
}
