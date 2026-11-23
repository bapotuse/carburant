import { mountSuspended } from '@nuxt/test-utils/runtime'
import { describe, expect, it } from 'vitest'
import PrixTotem from '../../app/composants/PrixTotem.vue'

/**
 * Le prix est l'element le plus important du site : son rendu et sa restitution aux
 * lecteurs d'ecran sont verrouilles par des tests.
 */
describe('PrixTotem', () => {
  it('decoupe le prix en entier, deux decimales et millieme', async () => {
    const composant = await mountSuspended(PrixTotem, { props: { prixEurL: 1.879 } })
    expect(composant.find('.prix__valeur').text()).toBe('1,879')
    expect(composant.find('.prix__millieme').text()).toBe('9')
  })

  it("garde trois decimales sur un prix rond : en station, 1,90 s'affiche 1,900", async () => {
    const composant = await mountSuspended(PrixTotem, { props: { prixEurL: 1.9 } })
    expect(composant.find('.prix__valeur').text()).toBe('1,900')
    expect(composant.find('.prix__millieme').text()).toBe('0')
  })

  it("expose au lecteur d'ecran la phrase entiere, pas le decoupage visuel", async () => {
    const composant = await mountSuspended(PrixTotem, { props: { prixEurL: 1.879 } })
    expect(composant.find('.lecteur-seul').text()).toBe('1,879 euro le litre')
  })

  it("masque les fragments visuels aux technologies d'assistance", async () => {
    const composant = await mountSuspended(PrixTotem, { props: { prixEurL: 1.879 } })
    expect(composant.find('.prix__valeur').attributes('aria-hidden')).toBe('true')
  })

  it('n\'emploie pas role="text", qui n\'existe pas dans la specification ARIA', async () => {
    const composant = await mountSuspended(PrixTotem, { props: { prixEurL: 1.879 } })
    expect(composant.html()).not.toContain('role="text"')
  })

  it('peut masquer son unite', async () => {
    const composant = await mountSuspended(PrixTotem, {
      props: { prixEurL: 1.879, avecUnite: false },
    })
    expect(composant.find('.prix__unite').exists()).toBe(false)
  })
})
