/**
 * Adresses et libellés de carburant.
 *
 * Le flux officiel publie les adresses **en capitales**. Les laisser telles quelles
 * donne un titre qui crie et se lit plus lentement — ce qui compte pour quelqu'un qui
 * cherche une station au volant.
 */
import { describe, expect, it } from 'vitest'
import { adresseLisible, libelleCarburant } from '../../app/composables/formats'

describe('adresseLisible', () => {
  it('met le type de voie en minuscules et le nom propre en capitale', () => {
    // La typographie française des adresses, qui n'est pas facultative :
    // « 32 Boulevard Schloesing » est de l'anglais déguisé.
    expect(adresseLisible('32 BOULEVARD SCHLOESING')).toBe('32 boulevard Schloesing')
    expect(adresseLisible('265 AVENUE DE MAZARGUES')).toBe('265 avenue de Mazargues')
    expect(adresseLisible('ROUTE DE LA MER')).toBe('route de la Mer')
  })

  it('préserve les sigles', () => {
    // « ZA » et « RN7 » sont des sigles ; « RUE » est un mot. La règle doit les
    // distinguer, sinon on obtient « Za la croix blanche » ou « RUE de Paris ».
    expect(adresseLisible('ZA LA CROIX BLANCHE')).toBe('ZA la Croix Blanche')
    expect(adresseLisible('RN7 LIEU-DIT LES PLATANES')).toBe('RN7 lieu-dit les Platanes')
    expect(adresseLisible('CC AUCHAN')).toBe('CC Auchan')
  })

  it('capitalise après un tiret et une apostrophe', () => {
    expect(adresseLisible('AVENUE SAINT-JEAN')).toBe('avenue Saint-Jean')
    expect(adresseLisible("RUE L'ABBE GREGOIRE")).toBe("rue L'Abbe Gregoire")
  })

  it('garde la particule en minuscules sauf en tête', () => {
    // « LA ROCHELLE » commence par une particule : elle prend la capitale, parce
    // qu'un libellé ne commence pas en minuscules.
    expect(adresseLisible('LA ROCHELLE')).toBe('La Rochelle')
    expect(adresseLisible('RUE DE LA GARE')).toBe('rue de la Gare')
  })

  it('ne touche pas aux nombres ni aux espaces multiples', () => {
    expect(adresseLisible('12  RUE  DES  LILAS')).toBe('12  rue  des  Lilas')
    expect(adresseLisible('  AVENUE DU PRADO  ')).toBe('avenue du Prado')
  })

  it('survit à une adresse vide ou étrange', () => {
    expect(adresseLisible('')).toBe('')
    expect(adresseLisible('   ')).toBe('')
    expect(adresseLisible('42')).toBe('42')
  })

  it('laisse une adresse déjà bien écrite lisible', () => {
    // Certaines stations ont une adresse en casse normale : elle ne doit pas être
    // abîmée par le passage dans la fonction.
    expect(adresseLisible('32 boulevard Schloesing')).toBe('32 boulevard Schloesing')
  })
})

describe('libelleCarburant', () => {
  it('traduit les six codes', () => {
    // `sp95` et `e10` sont des codes d'API : ils n'ont rien à faire à l'écran.
    expect(libelleCarburant('gazole')).toBe('Gazole')
    expect(libelleCarburant('e10')).toBe('SP95-E10')
    expect(libelleCarburant('gplc')).toBe('GPLc')
  })

  it('rend un code inconnu tel quel plutôt que vide', () => {
    // Si le flux publiait un septième carburant, mieux vaut afficher son code que rien.
    expect(libelleCarburant('hydrogene')).toBe('hydrogene')
  })
})
