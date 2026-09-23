export {}

declare global {
  interface FileSystemHandleLike {
    kind: 'file' | 'directory'
    name: string
    queryPermission?: (options: { mode: 'read' | 'readwrite' }) => Promise<'granted' | 'denied' | 'prompt'>
    requestPermission?: (options: { mode: 'read' | 'readwrite' }) => Promise<'granted' | 'denied' | 'prompt'>
  }

  interface FileSystemFileHandleLike extends FileSystemHandleLike {
    kind: 'file'
    getFile(): Promise<File>
    createWritable(): Promise<FileSystemWritableStreamLike>
  }

  interface FileSystemWritableStreamLike {
    write(data: Blob | ArrayBuffer | string): Promise<void>
    close(): Promise<void>
  }

  interface FileSystemDirectoryHandleLike extends FileSystemHandleLike {
    kind: 'directory'
    entries(): AsyncIterableIterator<[string, FileSystemHandleLike]>
    getFileHandle(name: string, options?: { create?: boolean }): Promise<FileSystemFileHandleLike>
    getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<FileSystemDirectoryHandleLike>
    removeEntry(name: string, options?: { recursive?: boolean }): Promise<void>
  }

  interface Window {
    showDirectoryPicker?: (options?: {
      mode?: 'read' | 'readwrite'
      startIn?: 'desktop' | 'documents' | 'downloads' | 'music' | 'pictures' | 'videos'
    }) => Promise<FileSystemDirectoryHandleLike>
  }
}
