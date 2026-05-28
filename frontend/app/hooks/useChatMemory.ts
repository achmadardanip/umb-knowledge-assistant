"use client";

import { useState } from "react";
import { getMemoryEnabled, setMemoryEnabled } from "../lib/localStorage";

export function useChatMemory() {
  const [enabled, setEnabledState] = useState(true);

  function hydrate() {
    setEnabledState(getMemoryEnabled());
  }

  function setEnabled(value: boolean) {
    setEnabledState(value);
    setMemoryEnabled(value);
  }

  return { enabled, hydrate, setEnabled };
}

