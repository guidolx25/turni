/**
 * The §9 / §12 Phase 5 gate: zero hardcoded user-visible strings.
 *
 * The ESLint rule (`i18next/no-literal-string`, mode `jsx-only`) catches raw
 * text and visible attributes *inside JSX*. It structurally cannot see a
 * sentence built in a variable, a helper, or a hook and rendered later through
 * an expression — which is exactly how hardcoded copy tends to survive. This
 * gate closes that half, so the two together cover the rule §9 states.
 *
 * It walks the real TypeScript AST rather than grepping, because a regex
 * cannot tell an import specifier from a sentence. A literal is reported only
 * when it sits in a value position the linter does not police AND reads like
 * human text. Everything it deliberately ignores is listed below, so the gate's
 * blind spots are legible instead of implicit.
 *
 * Escape hatch: `// i18n-gate-ignore` on (or just above) the line. Deliberately
 * visible and greppable — waiving one line should look like a decision.
 *
 * KNOWN GAP, stated rather than papered over: a SHORT single word assigned to a
 * variable (`const label = 'Salva'`) is not reported, because at that length it
 * is indistinguishable from the wire vocabulary the app is full of ('bagnino',
 * 'locked', 'pending', 'am'). In JSX such a word is still caught by the ESLint
 * rule; the uncovered case is a short word built in a variable and rendered
 * through an expression. Multi-word copy and anything ≥ 12 chars is covered.
 *
 * That is the ONLY gap. Three others were found by review and closed rather
 * than documented: interpolated templates (the literal parts of a
 * `TemplateExpression` are Head/Middle/Tail, not StringLiterals), all-lowercase
 * prose (the old CSS heuristic accepted "nessun turno pubblicato" as a class
 * list), and JSX attributes (the ESLint rule include-lists six visible ones, so
 * this gate exclude-lists the non-visible ones instead — opposite polarity, and
 * the safe direction to fail).
 *
 * Usage: node scripts/i18n-gate.mjs  →  exit 1 on any finding.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

import ts from 'typescript'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const SRC = join(ROOT, 'src')

/** The dictionaries ARE the strings; tests assert against them. */
const SKIP_FILES = [/src[/\\]i18n[/\\](it|en)\.ts$/, /\.test\.tsx?$/, /src[/\\]test[/\\]/]

/**
 * JSX attributes that never reach a human eye.
 *
 * The ESLint rule polices attributes with an INCLUDE-list of six visible ones,
 * so a newly-visible attribute (`aria-valuetext`, `aria-roledescription`,
 * `summary`, `download`) is not a finding there. This gate closes that polarity
 * gap: any JSX attribute NOT named here is checked, so an unfamiliar visible
 * attribute fails until someone consciously classifies it.
 */
const NON_VISIBLE_ATTRS = new Set([
  'className',
  'class',
  'id',
  'key',
  'type',
  'name',
  'htmlFor',
  'role',
  'to',
  'href',
  'src',
  'rel',
  'target',
  'method',
  'action',
  'autoComplete',
  'inputMode',
  'value',
  'data-testid',
  'viewBox',
  'xmlns',
  'fill',
  'stroke',
  'strokeWidth',
  'strokeLinecap',
  'strokeLinejoin',
  'd',
  'points',
  'transform',
  'aria-hidden',
  'tabIndex',
  'lang',
])

/** Calls whose string arguments are keys/paths, not prose. */
const KEY_TAKING_CALLERS = new Set(['t', 'useT', 'getItem', 'setItem', 'removeItem', 'request'])

function walkFiles(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walkFiles(full, out)
    else if (/\.tsx?$/.test(full)) out.push(full)
  }
  return out
}

/**
 * Does this literal read like something a person would read?
 *
 * Requires a letter plus either a space or real length, then rules out the
 * shapes that are structurally machine-facing: CSS class lists, identifiers,
 * codes, URLs and format patterns. Erring toward MORE findings is fine — a
 * false positive costs one `// i18n-gate-ignore`; a false negative ships
 * untranslated copy, which is the failure §9 exists to prevent.
 */
function looksLikeProse(text) {
  const trimmed = text.trim()
  if (!/[A-Za-zÀ-ÿ]/.test(trimmed)) return false
  if (trimmed.length < 4) return false
  // A dictionary key or an error code: dotted/snake/kebab, no spaces.
  if (!/\s/.test(trimmed) && /^[a-z0-9]+([._-][a-z0-9]+)*$/i.test(trimmed)) return false
  // A URL, path, or media/mime-ish value.
  if (/^([a-z]+:)?\/\//.test(trimmed) || trimmed.startsWith('/')) return false
  // Tailwind/CSS: every token is class-shaped. A CSS token carries a structural
  // character (`-`, `:`, `/`, `[`, `.`, …); a lowercase WORD does not — so
  // "nessun turno pubblicato" is prose while "flex items-center gap-2" is not.
  // Requiring that distinction, rather than just "all lowercase", is what stops
  // an entire class of untranslated copy from being waved through.
  const tokens = trimmed.split(/\s+/)
  const cssToken = /^[a-z0-9[\]()<>:._/\\%#-]+$/
  const structural = /[[\]():/\\%#.-]/
  const classLike =
    tokens.every((tok) => cssToken.test(tok)) && tokens.some((tok) => structural.test(tok))
  if (classLike) return false
  // Intl/date format patterns and single capitalised identifiers.
  if (/^[A-Za-z]+$/.test(trimmed) && trimmed.length < 12) return false
  // Real prose has a space, or is long enough to be a word a user reads.
  return /\s/.test(trimmed) || trimmed.length >= 12
}

/** Is this literal in a position the gate should police at all? */
function isCheckedPosition(node) {
  const parent = node.parent
  if (!parent) return false
  switch (parent.kind) {
    case ts.SyntaxKind.ImportDeclaration:
    case ts.SyntaxKind.ExportDeclaration:
    case ts.SyntaxKind.ImportType:
    case ts.SyntaxKind.LiteralType: // string-literal union members are wire values
    case ts.SyntaxKind.ModuleDeclaration:
      return false
    case ts.SyntaxKind.PropertyAssignment:
      // Object KEYS are identifiers; values still count.
      return parent.name !== node
    case ts.SyntaxKind.JsxAttribute: {
      // Not "the linter owns this": its include-list only covers six attributes,
      // so anything outside NON_VISIBLE_ATTRS is checked here instead.
      const attrName = ts.isIdentifier(parent.name) ? parent.name.text : parent.name.getText()
      return !NON_VISIBLE_ATTRS.has(attrName)
    }
    case ts.SyntaxKind.CallExpression: {
      const callee = parent.expression
      const name = ts.isIdentifier(callee)
        ? callee.text
        : ts.isPropertyAccessExpression(callee)
          ? callee.name.text
          : ''
      return !KEY_TAKING_CALLERS.has(name)
    }
    default:
      return true
  }
}

const findings = []
for (const file of walkFiles(SRC)) {
  const rel = relative(ROOT, file)
  if (SKIP_FILES.some((re) => re.test(file))) continue
  const text = readFileSync(file, 'utf8')
  const lines = text.split('\n')
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.ESNext, true, ts.ScriptKind.TSX)

  const report = (node, text) => {
    const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf))
    const own = lines[line] ?? ''
    const above = lines[line - 1] ?? ''
    if (!/i18n-gate-ignore/.test(own) && !/i18n-gate-ignore/.test(above)) {
      findings.push({ file: rel, line: line + 1, text })
    }
  }

  const visit = (node) => {
    const isString = ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)
    if (isString && isCheckedPosition(node) && looksLikeProse(node.text)) {
      report(node, node.text)
    }
    // An INTERPOLATED template (`Ciao ${name}, il turno è cambiato`) is a
    // TemplateExpression whose literal parts are Head/Middle/Tail nodes — none
    // of them a StringLiteral. Interpolated copy is exactly the shape prose
    // takes once it needs a value in it, so checking only plain literals would
    // miss the most likely hardcoded sentence in the codebase.
    if (ts.isTemplateExpression(node) && isCheckedPosition(node)) {
      const parts = [node.head, ...node.templateSpans.map((span) => span.literal)]
      const prose = parts.map((part) => part.text).filter((text) => looksLikeProse(text))
      if (prose.length > 0) {
        report(node, prose.join(' … '))
      }
    }
    // JSX text nodes are the ESLint rule's job, but a bare {'...'} expression
    // container is not an attribute and lands here — which is intended.
    ts.forEachChild(node, visit)
  }
  visit(sf)
}

// Also police the one thing the AST cannot see: a dictionary key present in one
// language and missing in the other. TypeScript's `satisfies` already enforces
// this at compile time and a vitest asserts it at runtime; this third check
// exists so the GATE itself is self-contained and does not depend on the other
// two still being wired up.
const dictKeys = (name) => {
  const src = readFileSync(join(SRC, 'i18n', `${name}.ts`), 'utf8')
  return new Set([...src.matchAll(/^\s*'([^']+)':/gm)].map((m) => m[1]))
}
const itKeys = dictKeys('it')
const enKeys = dictKeys('en')
const onlyIt = [...itKeys].filter((k) => !enKeys.has(k))
const onlyEn = [...enKeys].filter((k) => !itKeys.has(k))

if (findings.length === 0 && onlyIt.length === 0 && onlyEn.length === 0) {
  console.log(`i18n gate: clean (${itKeys.size} keys, both languages).`)
  process.exit(0)
}

for (const f of findings) {
  console.error(`${f.file}:${f.line}  hardcoded user-visible string: ${JSON.stringify(f.text)}`)
}
for (const k of onlyIt) console.error(`i18n/en.ts  missing key present in it.ts: ${k}`)
for (const k of onlyEn) console.error(`i18n/it.ts  missing key present in en.ts: ${k}`)
console.error(
  `\ni18n gate FAILED: ${findings.length} hardcoded string(s), ` +
    `${onlyIt.length + onlyEn.length} key-parity error(s).\n` +
    `Every user-visible string goes through it.ts/en.ts (spec §9). ` +
    `If a finding is genuinely not user-visible, add // i18n-gate-ignore on its line.`,
)
process.exit(1)
