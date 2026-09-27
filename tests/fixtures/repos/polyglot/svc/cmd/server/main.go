package main

import (
	"fmt"

	"example.com/svc/internal/store"
)

func main() {
	st := store.New()
	fmt.Println(st.Save(42))
}
