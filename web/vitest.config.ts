import { defineVitestConfig } from '@nuxt/test-utils/config'

export default defineVitestConfig({
  test: {
    environment: 'nuxt',
    include: ['tests/unitaires/**/*.test.ts'],
    environmentOptions: {
      nuxt: { domEnvironment: 'happy-dom' },
    },
  },
})
