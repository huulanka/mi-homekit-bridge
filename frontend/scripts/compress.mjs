// Pre-compress the build output. aiohttp serves `file.br` / `file.gz` when the
// browser accepts it, so the Pi never compresses on the fly.
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { brotliCompressSync, constants, gzipSync } from 'node:zlib'

const root = new URL('../../src/mi_homekit_bridge/static/', import.meta.url).pathname
const compressible = /\.(js|css|html|svg|webmanifest|json)$/

function walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) walk(path)
    else if (compressible.test(name) && statSync(path).size > 1024) {
      const data = readFileSync(path)
      writeFileSync(`${path}.gz`, gzipSync(data, { level: 9 }))
      writeFileSync(`${path}.br`, brotliCompressSync(data, { params: { [constants.BROTLI_PARAM_QUALITY]: 11 } }))
    }
  }
}

walk(root)
