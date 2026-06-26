import type { CodegenConfig } from '@graphql-codegen/cli';

// Prefer the live backend's introspection. Fallback to schema.graphql
// when the backend is not running locally (e.g., CI without Docker).
const LIVE_SCHEMA = 'http://localhost:8080/graphql';
const LOCAL_SCHEMA = './schema.graphql';

const schema = process.env.UC_CODEGEN_OFFLINE === '1' ? LOCAL_SCHEMA : LIVE_SCHEMA;

const config: CodegenConfig = {
  overwrite: true,
  schema,
  documents: ['src/queries/**/*.graphql'],
  generates: {
    'src/gql/generated/': {
      preset: 'client',
    },
  },
};

export default config;
