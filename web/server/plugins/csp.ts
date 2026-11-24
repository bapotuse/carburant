import { randomBytes } from 'node:crypto'

/**
 * Politique de securite du contenu (CSP), avec un nonce par requete.
 *
 * Pourquoi ici et pas dans Caddy : Nuxt emet deux scripts **en ligne** dans chaque
 * page rendue — la carte d'import (`type="importmap"`) et la configuration publique
 * (`window.__NUXT__.config`). Une politique `script-src 'self'` posee par le reverse
 * proxy les bloque, et le site reste a l'etat de page statique : aucune suggestion
 * d'adresse, aucun bouton qui repond. Mesure du 24/11/2026 : deux violations dans la
 * console et « Cannot read properties of undefined (reading 'app') ».
 *
 * Les trois sorties possibles etaient : ajouter `'unsafe-inline'`, ce qui revient a
 * ne plus avoir de politique ; calculer les empreintes des scripts a la construction
 * et les recopier dans le proxy, ce qui casse au premier changement de configuration ;
 * ou donner un nonce a chaque requete. C'est la troisieme, et elle tient en vingt
 * lignes sans dependance.
 *
 * Le nonce doit etre **imprevisible et different a chaque reponse** : un nonce fixe
 * ne protege de rien. `randomBytes` est le generateur cryptographique de Node.
 */

/** Ce que la page a le droit de charger. `{nonce}` est remplace a chaque requete. */
function politique(nonce: string): string {
  return [
    "default-src 'self'",
    // `data:` pour les SVG en ligne, `blob:` pour les tuiles de MapLibre (Jalon 5).
    "img-src 'self' data: blob:",
    // `unsafe-inline` reste necessaire pour les styles : Vue pose des attributs
    // `style` calcules (la couleur d'une pastille de carburant, par exemple), et un
    // attribut de style releve de `style-src`. Les feuilles, elles, sont externes
    // (`features.inlineStyles: false` dans nuxt.config.ts).
    "style-src 'self' 'unsafe-inline'",
    "font-src 'self'",
    `script-src 'self' 'nonce-${nonce}'`,
    "connect-src 'self'",
    "worker-src 'self' blob:",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join('; ')
}

/** Ajoute le nonce a tout `<script>` en ligne, c'est-a-dire sans attribut `src`. */
function marquer(fragment: string, nonce: string): string {
  return fragment.replace(/<script(?![^>]*\ssrc=)/g, `<script nonce="${nonce}"`)
}

export default defineNitroPlugin((nitro) => {
  nitro.hooks.hook('render:html', (html, { event }) => {
    const nonce = randomBytes(16).toString('base64')
    for (const partie of ['head', 'bodyPrepend', 'bodyAppend'] as const) {
      html[partie] = html[partie].map((fragment) => marquer(fragment, nonce))
    }
    setResponseHeader(event, 'Content-Security-Policy', politique(nonce))
  })
})
