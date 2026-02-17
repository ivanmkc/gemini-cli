
def calculateTotal( items ):
  t = 0
  for i in range(len(items)):
    if items[i]['type'] == 'food':
       t = t + items[i]['price']
    if items[i]['type'] == 'electronics':
       t = t + (items[i]['price'] * 1.2) # tax
  return t
