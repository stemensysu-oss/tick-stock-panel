/** Build the real page as a self-contained, read-only fictional demo. */
import { execFileSync } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const frontend = path.join(root, 'frontend')
const output = path.resolve(process.argv[2] || path.join(root, 'dist', 'TSP-multi-asset-preview.html'))
const python = process.env.TSP_PYTHON || path.join(root, 'backend', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const fixtures = JSON.parse(execFileSync(python, [path.join(root, 'scripts', 'multi_asset_preview_data.py')], {
  cwd: root, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024,
}))
const scratch = path.join(frontend, 'node_modules', '.cache', 'tsp-multi-asset-preview')
await mkdir(scratch, { recursive: true })
const entry = path.join(scratch, 'entry.tsx')
await writeFile(entry, `
import React from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { MultiAssetPage } from '@/custom/multi-asset/MultiAssetPage'
import { api } from '@/lib/api'
import { ToastContainer } from '@/components/Toast'
import '@/index.css'
const fixtures = ${JSON.stringify(fixtures).replaceAll('<', '\\u003c')}
api.multiAssetCatalog = async () => structuredClone(fixtures.catalog)
api.multiAssetSnapshot = async (category, mode) => structuredClone(fixtures.snapshots[category][mode])
const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } })
function Preview() {
  const [dark, setDark] = React.useState(true)
  return <QueryClientProvider client={client}><MemoryRouter>
    <header className="preview-header"><strong>TSP · 多资产工作台</strong><span>离线交互预览</span>
    <button onClick={() => { document.documentElement.classList.toggle('dark'); setDark(!dark) }}>{dark ? '浅色模式' : '深色模式'}</button></header>
    <main className="preview-shell"><MultiAssetPage previewOnly /></main><ToastContainer />
  </MemoryRouter></QueryClientProvider>
}
createRoot(document.getElementById('root')!).render(<Preview />)
`, 'utf8')
process.chdir(frontend)
const { build } = await import(pathToFileURL(path.join(frontend, 'node_modules/vite/dist/node/index.js')).href)
const { default: react } = await import(pathToFileURL(path.join(frontend, 'node_modules/@vitejs/plugin-react/dist/index.js')).href)
const result = await build({
  configFile: false, root: frontend, publicDir: false, plugins: [react()],
  resolve: { alias: { '@': path.join(frontend, 'src') } },
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: { write: false, minify: 'esbuild', sourcemap: false, cssCodeSplit: false,
    lib: { entry, name: 'TspMultiAssetPreview', formats: ['iife'] },
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
})
const files = (Array.isArray(result) ? result : [result]).flatMap(item => item.output)
const js = files.filter(item => item.type === 'chunk').map(item => item.code).join('\n')
const css = files.filter(item => item.type === 'asset' && item.fileName.endsWith('.css')).map(item => item.source).join('\n')
if (!js || !css) throw new Error('Preview build did not produce both JavaScript and CSS')
const html = `<!doctype html><html lang="zh-CN" class="dark"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>TSP 多资产工作台 · 离线演示</title><style>${css.replaceAll('</style', '<\\/style')}
.preview-header{display:flex;align-items:center;gap:18px;flex-wrap:wrap;padding:18px 24px;border-bottom:1px solid hsl(var(--border));font-size:13px}.preview-header strong{font-size:16px}.preview-header span{color:hsl(var(--fg-muted))}.preview-header button{margin-left:auto;border:1px solid hsl(var(--border));border-radius:6px;padding:6px 12px}.preview-shell{max-width:1640px;margin:auto;padding:24px;min-width:0}@media(max-width:640px){.preview-shell{padding:12px}.preview-header{padding:12px}}
</style></head><body><div id="root"></div><script>${js.replaceAll('</script', '<\\/script')}</script></body></html>`
await mkdir(path.dirname(output), { recursive: true })
await writeFile(output, html, 'utf8')
console.log(`Preview: ${output} (${Buffer.byteLength(html)} bytes)`)
