/**
 * Bible RAG - Application Root Component
 *
 * The main application component that sets up routing.
 * Provider wrappers (QueryClientProvider, ErrorBoundary) are in main.tsx.
 */

import { RouterProvider } from 'react-router-dom';
import { router } from './router';

function App() {
  return <RouterProvider router={router} />;
}

export default App;
