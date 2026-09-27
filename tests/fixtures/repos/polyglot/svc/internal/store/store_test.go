package store

import "testing"

func TestSave(t *testing.T) {
	s := New()
	s.Save(1)
}
