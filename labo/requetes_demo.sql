select id from jobs where status = $1 order by created_at limit 10

select id, status from jobs where id = $1

select c.segment, p.categorie, sum(l.qte * o.montant) from client c join commande o on o.client_id = c.id join ligne l on l.commande_id = o.id join produit p on p.code = l.produit where c.id = $1 group by 1, 2
