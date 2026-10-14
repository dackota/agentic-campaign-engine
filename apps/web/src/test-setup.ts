import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Testing Library only unmounts by itself when the test globals are on; they are off here.
afterEach(cleanup);
