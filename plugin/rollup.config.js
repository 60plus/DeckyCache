import deckyPlugin from "@decky/rollup";

// The Decky preset knows the entry point, externalises react, react-dom and
// the modules the loader injects at runtime, and puts the bundle where the
// loader looks for it. It reads plugin.json for the manifest, so nothing here
// repeats what is already declared there.
//
// It is the package's default export, not a named `defineConfig`.
export default deckyPlugin();
